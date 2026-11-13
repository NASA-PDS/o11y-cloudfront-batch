"""Unit tests for scripts/logstash-deploy.sh: the required LOG_YEARS check."""
import os
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_SCRIPT = os.path.join(REPO_ROOT, "scripts", "logstash-deploy.sh")


@unittest.skipIf(os.geteuid() == 0, "the deploy script refuses to run as root before it checks LOG_YEARS")
class TestDeployRequiresLogYears(unittest.TestCase):
    """The deploy must stop before it touches AWS or the repo when LOG_YEARS is missing.

    Only the failing cases are run: a valid LOG_YEARS lets the script continue to the Logstash install check
    and then to AWS and systemd calls.
    """

    def run_deploy(self, **extra_env):
        """Run the deploy script with a minimal environment and return the completed process."""
        env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")}
        env.update(extra_env)
        return subprocess.run(["bash", DEPLOY_SCRIPT], env=env, capture_output=True, text=True, timeout=30)

    def assert_requires_log_years(self, result):
        """Assert the script exited 1 with the LOG_YEARS error before doing anything else."""
        self.assertEqual(1, result.returncode)
        self.assertIn("LOG_YEARS is required", result.stderr)
        self.assertNotIn("=== o11y-cloudfront-batch Logstash deploy ===", result.stdout)

    def test_unset_log_years_is_rejected(self):
        """A deploy with LOG_YEARS unset exits with the error."""
        self.assert_requires_log_years(self.run_deploy())

    def test_empty_log_years_is_rejected(self):
        """A deploy with LOG_YEARS set to an empty string exits with the error."""
        self.assert_requires_log_years(self.run_deploy(LOG_YEARS=""))

    def test_separators_only_is_rejected(self):
        """A LOG_YEARS made only of spaces and commas counts as empty."""
        self.assert_requires_log_years(self.run_deploy(LOG_YEARS=" , ,"))


if __name__ == "__main__":
    unittest.main()
