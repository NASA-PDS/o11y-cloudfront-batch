"""Unit tests for config/opensearch/ecs-8.17-custom-template.json."""
import json
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(REPO_ROOT, "config", "opensearch", "ecs-8.17-custom-template.json")


class TestOpenSearchTemplate(unittest.TestCase):
    """The template must not let log content grow an index's mapping without bound."""

    @classmethod
    def setUpClass(cls):
        """Load the template mappings once."""
        with open(TEMPLATE) as f:
            cls.mappings = json.load(f)["template"]["mappings"]

    def test_query_params_is_flat_object(self):
        """Every distinct query parameter name must not become its own mapped field."""
        query_params = self.mappings["properties"]["url"]["properties"]["query_params"]
        self.assertEqual("flat_object", query_params["type"])
        self.assertNotIn("dynamic", query_params)

    def test_no_dynamic_template_maps_query_param_subfields(self):
        """A flat_object has no mapped subfields, so a dynamic template for them has nothing to apply to."""
        for template in self.mappings["dynamic_templates"]:
            for name, rule in template.items():
                self.assertNotIn("query_params", rule.get("path_match", ""), name)


if __name__ == "__main__":
    unittest.main()
