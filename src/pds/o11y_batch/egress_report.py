"""Daily egress (download volume) report for PDS web analytics."""
import argparse
import json
import logging
import os
import smtplib
from datetime import datetime
from datetime import timezone
from email.mime.text import MIMEText
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import boto3  # type: ignore
import requests
from botocore.auth import SigV4Auth  # type: ignore
from botocore.awsrequest import AWSRequest  # type: ignore

logger = logging.getLogger(__name__)

BYTES_PER_GB = 1_000_000_000.0
SMTP_CONFIG_FIELDS = ("username", "password", "server", "sender")


class EgressReporter:
    """Queries OpenSearch for download-volume metrics and emails a summary report.

    SMTP credentials (username, password, server, sender) are resolved via
    _resolve_smtp_config(), then sent via AWS SES's SMTP endpoint with smtplib.
    Two sources are supported, checked in this order:

    1. A local KEY=VALUE file (smtp_env_file) — no AWS permissions needed beyond
       reading a file already on disk. This is the default/recommended path.
    2. AWS SSM Parameter Store (smtp_config_ssm_path) — mirrors data-upload-manager's
       send_email() (pds_status_app.py), but requires the caller's IAM role to have
       ssm:GetParametersByPath/GetParameter on that path.

    Attributes:
        opensearch_endpoint (str): OpenSearch domain endpoint, without scheme (e.g. "search-foo.us-west-2.es.amazonaws.com").
        index_pattern (str): Index pattern to query (e.g. "pds-weblogs*").
        region (str): AWS region the OpenSearch domain lives in.
        smtp_env_file (Optional[str]): Path to a local KEY=VALUE file holding the SMTP credentials. Checked first.
        smtp_config_ssm_path (Optional[str]): SSM parameter path prefix holding the SMTP credentials. Fallback.
        recipients (List[str]): Recipient email addresses for the report.
        hours (int): Trailing window, in hours, the report covers.
        dry_run (bool): If True, skip sending the email entirely (query + build only).
        output_file (Optional[str]): If set, write the HTML report to this local path.
    """

    def __init__(
        self,
        opensearch_endpoint: str,
        index_pattern: str,
        region: str,
        recipients: List[str],
        smtp_env_file: Optional[str] = None,
        smtp_config_ssm_path: Optional[str] = None,
        hours: int = 24,
        dry_run: bool = False,
        output_file: Optional[str] = None,
    ) -> None:
        """Initialize the reporter with query and delivery configuration."""
        self.opensearch_endpoint = opensearch_endpoint
        self.index_pattern = index_pattern
        self.region = region
        self.smtp_env_file = smtp_env_file
        self.smtp_config_ssm_path = smtp_config_ssm_path
        self.recipients = recipients
        self.hours = hours
        self.dry_run = dry_run
        self.output_file = output_file

    def _build_query(self) -> Dict[str, Any]:
        """Build the OpenSearch aggregation query for the configured time window.

        Mirrors the "Download Volume - Metric", "Download Volume - Top 20 Domains", and
        "Download Volume - Top 20 Users" visualizations from the "Archive Downloads
        Monitoring" Dashboards dashboard: sum of http.response.body.bytes (converted to
        GB), broken down by source.registered_domain and source.domain.

        Returns:
            Dict[str, Any]: The OpenSearch _search request body.
        """
        return {
            "size": 0,
            "query": {
                "range": {
                    "@timestamp": {
                        "gte": "now-%dh" % self.hours,
                        "lte": "now",
                    }
                }
            },
            "aggs": {
                "total_gb": {"sum": {"field": "http.response.body.bytes"}},
                "top_domains": {
                    "terms": {
                        "field": "source.registered_domain",
                        "size": 20,
                        "order": {"gb": "desc"},
                    },
                    "aggs": {"gb": {"sum": {"field": "http.response.body.bytes"}}},
                },
                "top_users": {
                    "terms": {
                        "field": "source.domain",
                        "size": 20,
                        "order": {"gb": "desc"},
                    },
                    "aggs": {"gb": {"sum": {"field": "http.response.body.bytes"}}},
                },
            },
        }

    def _sign_request(self, method: str, url: str, body: str) -> Dict[str, str]:
        """Sign a request to the OpenSearch domain with SigV4, using the instance's IAM role.

        Mirrors the `--aws-sigv4` curl auth in scripts/logstash-deploy.sh and the
        `auth_type: aws_iam` block in config/logstash/config/shared/pds-output-opensearch.conf.

        Args:
            method (str): HTTP method.
            url (str): Full request URL.
            body (str): Raw request body.

        Returns:
            Dict[str, str]: Signed headers to send with the request.
        """
        credentials = boto3.Session().get_credentials()
        request = AWSRequest(method=method, url=url, data=body, headers={"Content-Type": "application/json"})
        SigV4Auth(credentials, "es", self.region).add_auth(request)
        return dict(request.headers)

    def query_egress(self) -> Dict[str, Any]:
        """Run the aggregation query against OpenSearch.

        Returns:
            Dict[str, Any]: The parsed OpenSearch _search response.
        """
        url = f"https://{self.opensearch_endpoint}/{self.index_pattern}/_search"
        payload = json.dumps(self._build_query())
        headers = self._sign_request("POST", url, payload)

        response = requests.post(url, data=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def build_email_html(self, response: Dict[str, Any]) -> str:
        """Render the aggregation response as an HTML email body.

        Args:
            response (Dict[str, Any]): The OpenSearch _search response from query_egress().

        Returns:
            str: HTML email body.
        """
        aggs = response.get("aggregations", {})
        total_gb = aggs.get("total_gb", {}).get("value") or 0.0
        window_end = datetime.now(timezone.utc)

        def render_table(agg_name: str, label: str) -> str:
            buckets = aggs.get(agg_name, {}).get("buckets", [])
            rows = "".join(
                f"<tr><td>{b['key']}</td><td>{b['gb']['value']:.2f}</td><td>{b['doc_count']}</td></tr>"
                for b in buckets
            )
            return (
                f"<h3>{label}</h3>"
                "<table border='1' cellpadding='4' cellspacing='0'>"
                f"<tr><th>{label}</th><th>GB Downloaded</th><th>Requests</th></tr>"
                f"{rows}"
                "</table>"
            )

        return (
            f"<p>Egress report for the {self.hours}h window ending {window_end.isoformat()}.</p>"
            f"<h2>Total Download Volume: {total_gb:.2f} GB</h2>"
            f"{render_table('top_domains', 'Top 20 Domains')}"
            f"{render_table('top_users', 'Top 20 Users')}"
        )

    def _read_smtp_env_file(self, path: str) -> Dict[str, str]:
        """Read SMTP credentials from a local KEY=VALUE file.

        Blank lines and lines starting with "#" are ignored. Values may optionally be
        wrapped in matching single or double quotes.

        Args:
            path (str): Path to the KEY=VALUE file.

        Returns:
            Dict[str, str]: SMTP config with "username", "password", "server", "sender" keys.

        Raises:
            RuntimeError: If the expected SMTP fields are not found in the file.
        """
        smtp_config = {}
        with open(path) as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                smtp_config[key.strip()] = value.strip().strip("'\"")

        if not all(field in smtp_config for field in SMTP_CONFIG_FIELDS):
            raise RuntimeError(
                f"Unexpected SMTP configuration in {path}, expected {SMTP_CONFIG_FIELDS}, "
                f"got {list(smtp_config.keys())}"
            )

        return smtp_config

    def _fetch_smtp_config_from_ssm(self) -> Dict[str, str]:
        """Pull SMTP endpoint credentials from SSM Parameter Store.

        Mirrors data-upload-manager's send_email() (src/pds/ingress/service/pds_status_app.py).
        Requires ssm:GetParametersByPath/GetParameter on smtp_config_ssm_path.

        Returns:
            Dict[str, str]: SMTP config with "username", "password", "server", "sender" keys.

        Raises:
            RuntimeError: If the expected SMTP endpoint parameters are not found under the
                configured SSM path.
        """
        ssm_client = boto3.client("ssm", region_name=self.region)
        response = ssm_client.get_parameters_by_path(
            Path=self.smtp_config_ssm_path, Recursive=True, WithDecryption=True
        )

        smtp_config = {}
        for ssm_parameter in response["Parameters"]:
            smtp_config[ssm_parameter["Name"].split("/")[-1]] = ssm_parameter["Value"]

        if not all(field in smtp_config for field in SMTP_CONFIG_FIELDS):
            raise RuntimeError(
                f"Unexpected SMTP configuration from SSM path {self.smtp_config_ssm_path}, "
                f"expected {SMTP_CONFIG_FIELDS}, got {list(smtp_config.keys())}"
            )

        return smtp_config

    def _resolve_smtp_config(self) -> Dict[str, str]:
        """Resolve SMTP credentials, preferring the local env file over SSM.

        Returns:
            Dict[str, str]: SMTP config with "username", "password", "server", "sender" keys.

        Raises:
            RuntimeError: If neither smtp_env_file nor smtp_config_ssm_path is configured.
        """
        if self.smtp_env_file:
            return self._read_smtp_env_file(self.smtp_env_file)
        if self.smtp_config_ssm_path:
            return self._fetch_smtp_config_from_ssm()
        raise RuntimeError("No SMTP config source configured — set smtp_env_file or smtp_config_ssm_path.")

    def send_email(self, html_body: str) -> None:
        """Send the report via AWS SES's SMTP endpoint.

        Args:
            html_body (str): HTML email body built by build_email_html().
        """
        smtp_config = self._resolve_smtp_config()

        message = MIMEText(html_body, "html")
        message["Subject"] = f"PDS Egress Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        message["From"] = smtp_config["sender"]
        message["To"] = ", ".join(self.recipients)

        endpoint_host, endpoint_port = smtp_config["server"].split(":")

        with smtplib.SMTP(endpoint_host, int(endpoint_port)) as endpoint:
            endpoint.starttls()
            endpoint.login(smtp_config["username"], smtp_config["password"])
            endpoint.sendmail(smtp_config["sender"], self.recipients, message.as_string())

    def run(self) -> None:
        """Query OpenSearch, build the report, and (unless dry_run) email it."""
        response = self.query_egress()
        html_body = self.build_email_html(response)
        total_gb = response.get("aggregations", {}).get("total_gb", {}).get("value") or 0.0

        if self.output_file:
            with open(self.output_file, "w") as f:
                f.write(html_body)
            logger.info("Report written to %s", self.output_file)

        if self.dry_run:
            logger.info("Dry run: %.2f GB over %dh window — email not sent.", total_gb, self.hours)
            return

        self.send_email(html_body)
        logger.info(
            "Egress report sent: %.2f GB over %dh window, %d recipient(s)",
            total_gb,
            self.hours,
            len(self.recipients),
        )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for the script.

    Returns a Namespace object with parsed arguments if successful;
    otherwise, prints an error message and exits the script with a non-zero status.
    """
    parser = argparse.ArgumentParser(
        description="Query OpenSearch for PDS download-volume metrics and email a daily report.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--opensearch-endpoint", required=True, help="OpenSearch domain endpoint (without https://).")
    parser.add_argument("--index-pattern", default="pds-weblogs*", help="Index pattern to query.")
    parser.add_argument("--region", default="us-west-2", help="AWS region for OpenSearch and (if used) SSM.")
    parser.add_argument(
        "--smtp-env-file",
        default=os.environ.get("SMTP_ENV_FILE"),
        help="Path to a local KEY=VALUE file holding the SMTP credentials (username, password, server, sender). "
        "Checked before --smtp-config-ssm-path. Defaults to the SMTP_ENV_FILE env var if set.",
    )
    parser.add_argument(
        "--smtp-config-ssm-path",
        default=os.environ.get("SMTP_CONFIG_SSM_KEY_PATH"),
        help="SSM parameter path prefix holding the SMTP credentials (username, password, server, sender). "
        "Only used if --smtp-env-file is not set/found. Defaults to the SMTP_CONFIG_SSM_KEY_PATH env var if set. "
        "Requires ssm:GetParametersByPath/GetParameter on this path.",
    )
    parser.add_argument(
        "--recipients", default="", help="Comma-separated list of report recipient addresses. Required unless --dry-run."
    )
    parser.add_argument("--hours", type=int, default=24, help="Trailing window, in hours, the report covers.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query and build the report but do not send an email. No SMTP config needed. "
        "Combine with --output-file to inspect the generated HTML.",
    )
    parser.add_argument("--output-file", default=None, help="If set, write the generated HTML report to this path.")

    args = parser.parse_args()
    if not args.dry_run:
        if not args.recipients:
            parser.error("--recipients is required unless --dry-run is set.")
        if not args.smtp_env_file and not args.smtp_config_ssm_path:
            parser.error(
                "Either --smtp-env-file/SMTP_ENV_FILE or --smtp-config-ssm-path/SMTP_CONFIG_SSM_KEY_PATH is required "
                "unless --dry-run is set."
            )

    return args


def main() -> None:
    """Main entry point for the CLI."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    args = parse_args()
    recipients = [r.strip() for r in args.recipients.split(",") if r.strip()]

    reporter = EgressReporter(
        opensearch_endpoint=args.opensearch_endpoint,
        index_pattern=args.index_pattern,
        region=args.region,
        recipients=recipients,
        smtp_env_file=args.smtp_env_file,
        smtp_config_ssm_path=args.smtp_config_ssm_path,
        hours=args.hours,
        dry_run=args.dry_run,
        output_file=args.output_file,
    )
    reporter.run()


if __name__ == "__main__":
    main()
