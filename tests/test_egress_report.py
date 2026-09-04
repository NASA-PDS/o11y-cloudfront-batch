"""Unit tests for the EgressReporter class."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pds.o11y_batch.egress_report import EgressReporter

SAMPLE_RESPONSE = {
    "aggregations": {
        "total_gb": {"value": 123.456},
        "top_domains": {
            "buckets": [
                {"key": "example.com", "doc_count": 10, "gb": {"value": 5.0}},
                {"key": "other.org", "doc_count": 3, "gb": {"value": 1.0}},
            ]
        },
        "top_users": {
            "buckets": [
                {"key": "user.example.com", "doc_count": 4, "gb": {"value": 2.0}},
            ]
        },
    }
}


def make_reporter(**overrides):
    """Build an EgressReporter with sane defaults for testing."""
    kwargs = dict(
        opensearch_endpoint="search-foo.us-west-2.es.amazonaws.com",
        index_pattern="pds-weblogs*",
        region="us-west-2",
        smtp_config_ssm_path="/pds/dum/smtp/",
        recipients=["ops@example.com"],
        hours=24,
    )
    kwargs.update(overrides)
    return EgressReporter(**kwargs)


class TestEgressReporter(unittest.TestCase):
    """Test cases for the EgressReporter class."""

    def test_build_query_shape(self):
        """The query should filter on the trailing window and request all three aggregations."""
        reporter = make_reporter(hours=12)
        query = reporter._build_query()

        self.assertEqual(query["size"], 0)
        self.assertEqual(query["query"]["range"]["@timestamp"]["gte"], "now-12h")
        self.assertIn("total_gb", query["aggs"])
        self.assertEqual(query["aggs"]["total_gb"]["sum"]["field"], "http.response.body.bytes")
        self.assertEqual(query["aggs"]["top_domains"]["terms"]["field"], "source.registered_domain")
        self.assertEqual(query["aggs"]["top_domains"]["terms"]["size"], 20)
        self.assertEqual(query["aggs"]["top_users"]["terms"]["field"], "source.domain")

    @patch("pds.o11y_batch.egress_report.requests.post")
    @patch("pds.o11y_batch.egress_report.SigV4Auth")
    @patch("pds.o11y_batch.egress_report.boto3.Session")
    def test_query_egress_calls_signed_post(self, mock_session, mock_sigv4, mock_post):
        """query_egress should POST the query body to the domain's _search endpoint and return parsed JSON."""
        mock_session.return_value.get_credentials.return_value = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_RESPONSE
        mock_post.return_value = mock_response

        reporter = make_reporter()
        result = reporter.query_egress()

        self.assertEqual(result, SAMPLE_RESPONSE)
        mock_post.assert_called_once()
        called_url = mock_post.call_args.args[0]
        self.assertEqual(called_url, "https://search-foo.us-west-2.es.amazonaws.com/pds-weblogs*/_search")
        mock_response.raise_for_status.assert_called_once()

    def test_build_email_html_includes_totals_and_rows(self):
        """The HTML body should surface the total GB figure and each bucket's key."""
        reporter = make_reporter()
        html = reporter.build_email_html(SAMPLE_RESPONSE)

        self.assertIn("123.46 GB", html)
        self.assertIn("example.com", html)
        self.assertIn("user.example.com", html)

    @patch("pds.o11y_batch.egress_report.boto3.client")
    def test_fetch_smtp_config_from_ssm_success(self, mock_boto_client):
        """SSM parameters under the configured path should be mapped to their unique name suffix."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameters_by_path.return_value = {
            "Parameters": [
                {"Name": "/pds/dum/smtp/username", "Value": "smtp-user"},
                {"Name": "/pds/dum/smtp/password", "Value": "smtp-pass"},
                {"Name": "/pds/dum/smtp/server", "Value": "email-smtp.us-west-2.amazonaws.com:587"},
                {"Name": "/pds/dum/smtp/sender", "Value": "noreply@example.com"},
            ]
        }
        mock_boto_client.return_value = mock_ssm

        reporter = make_reporter()
        config = reporter._fetch_smtp_config_from_ssm()

        self.assertEqual(config["username"], "smtp-user")
        self.assertEqual(config["server"], "email-smtp.us-west-2.amazonaws.com:587")

    @patch("pds.o11y_batch.egress_report.boto3.client")
    def test_fetch_smtp_config_from_ssm_missing_field_raises(self, mock_boto_client):
        """Missing an expected SMTP field should raise RuntimeError rather than fail later with a KeyError."""
        mock_ssm = MagicMock()
        mock_ssm.get_parameters_by_path.return_value = {
            "Parameters": [{"Name": "/pds/dum/smtp/username", "Value": "smtp-user"}]
        }
        mock_boto_client.return_value = mock_ssm

        reporter = make_reporter()
        with self.assertRaises(RuntimeError):
            reporter._fetch_smtp_config_from_ssm()

    def test_read_smtp_env_file_success(self):
        """A local KEY=VALUE file should be parsed into the SMTP config dict, ignoring blanks/comments/quotes."""
        content = (
            "# SMTP config\n"
            "\n"
            "username=smtp-user\n"
            "password='smtp-pass'\n"
            'server="email-smtp.us-west-2.amazonaws.com:587"\n'
            "sender=noreply@example.com\n"
        )
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
            f.write(content)
            path = f.name
        try:
            reporter = make_reporter(smtp_config_ssm_path=None, smtp_env_file=path)
            config = reporter._read_smtp_env_file(path)
            self.assertEqual(
                config,
                {
                    "username": "smtp-user",
                    "password": "smtp-pass",
                    "server": "email-smtp.us-west-2.amazonaws.com:587",
                    "sender": "noreply@example.com",
                },
            )
        finally:
            os.remove(path)

    def test_read_smtp_env_file_missing_field_raises(self):
        """Missing an expected SMTP field in the env file should raise RuntimeError."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
            f.write("username=smtp-user\n")
            path = f.name
        try:
            reporter = make_reporter(smtp_config_ssm_path=None, smtp_env_file=path)
            with self.assertRaises(RuntimeError):
                reporter._read_smtp_env_file(path)
        finally:
            os.remove(path)

    def test_resolve_smtp_config_prefers_env_file_over_ssm(self):
        """When both sources are configured, the local env file should win and SSM should not be called."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
            f.write("username=u\npassword=p\nserver=s:587\nsender=se\n")
            path = f.name
        try:
            reporter = make_reporter(smtp_env_file=path, smtp_config_ssm_path="/pds/dum/smtp/")
            with patch.object(reporter, "_fetch_smtp_config_from_ssm") as mock_ssm_fetch:
                config = reporter._resolve_smtp_config()
                mock_ssm_fetch.assert_not_called()
            self.assertEqual(config["username"], "u")
        finally:
            os.remove(path)

    def test_resolve_smtp_config_raises_without_any_source(self):
        """With neither source configured, resolving SMTP config should fail clearly."""
        reporter = make_reporter(smtp_config_ssm_path=None, smtp_env_file=None)
        with self.assertRaises(RuntimeError):
            reporter._resolve_smtp_config()

    @patch("pds.o11y_batch.egress_report.smtplib.SMTP")
    @patch.object(EgressReporter, "_resolve_smtp_config")
    def test_send_email_uses_smtp_with_starttls_and_login(self, mock_resolve_config, mock_smtp_cls):
        """send_email should STARTTLS, log in, and send to all recipients via the resolved SMTP config."""
        mock_resolve_config.return_value = {
            "username": "smtp-user",
            "password": "smtp-pass",
            "server": "email-smtp.us-west-2.amazonaws.com:587",
            "sender": "noreply@example.com",
        }
        mock_endpoint = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_endpoint

        reporter = make_reporter(recipients=["a@example.com", "b@example.com"])
        reporter.send_email("<p>report</p>")

        mock_smtp_cls.assert_called_once_with("email-smtp.us-west-2.amazonaws.com", 587)
        mock_endpoint.starttls.assert_called_once()
        mock_endpoint.login.assert_called_once_with("smtp-user", "smtp-pass")
        mock_endpoint.sendmail.assert_called_once()
        sender_arg, recipients_arg, _message = mock_endpoint.sendmail.call_args.args
        self.assertEqual(sender_arg, "noreply@example.com")
        self.assertEqual(recipients_arg, ["a@example.com", "b@example.com"])

    @patch.object(EgressReporter, "send_email")
    @patch.object(EgressReporter, "query_egress")
    def test_run_dry_run_writes_output_file_and_skips_email(self, mock_query, mock_send_email):
        """--dry-run should write the report to output_file (if set) and never call send_email."""
        mock_query.return_value = SAMPLE_RESPONSE
        with tempfile.NamedTemporaryFile("r", delete=False, suffix=".html") as f:
            path = f.name
        try:
            reporter = make_reporter(smtp_env_file=None, smtp_config_ssm_path=None, dry_run=True, output_file=path)
            reporter.run()

            mock_send_email.assert_not_called()
            with open(path) as f:
                content = f.read()
            self.assertIn("123.46 GB", content)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
