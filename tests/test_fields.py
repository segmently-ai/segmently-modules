import unittest

from segmently_modules.fields import (CORE_FIELDS, check_type, load_field_defs, to_json_schema,
                           value_matches)
from segmently_modules.output import UsageError


class TypeCheckTest(unittest.TestCase):
    def test_nested_arrays_and_maps(self):
        self.assertTrue(check_type("string[][]", [["a", "b"], ["c"]]))
        self.assertFalse(check_type("string[][]", ["a"]))
        self.assertTrue(check_type("map<string,string[]>", {"k": ["x"]}))
        self.assertFalse(check_type("map<string,string[]>", {"k": "x"}))
        self.assertFalse(check_type("int", True))

    def test_union_accepts_both_negative_keyword_shapes(self):
        nk = CORE_FIELDS["negative_keywords"]
        self.assertTrue(value_matches(nk, {"order": ["order of operations"]}))
        self.assertTrue(value_matches(nk, ["order of operations"]))
        self.assertFalse(value_matches(nk, "order"))

    def test_scalar_partitions(self):  # AC-012
        cases = [("string", "a", True), ("string", 1, False),
                 ("bool", True, True), ("bool", 1, False),
                 ("int", 1, True), ("int", True, False),
                 ("object", {}, True), ("object", [], False),
                 ("string[]", ["a"], True), ("string[]", "a", False)]
        for expr, value, expected in cases:
            with self.subTest(expr=expr, value=value):
                self.assertEqual(check_type(expr, value), expected)


class LoadFieldDefsTest(unittest.TestCase):
    def test_declared_field_is_added_with_owner(self):
        defs = load_field_defs({"fields": {"file_paths": {
            "type": "string[]", "kind": "code_pointer", "owner": "bookshop"}}})
        self.assertEqual(defs["file_paths"].kind, "code_pointer")
        self.assertEqual(defs["file_paths"].owner, "bookshop")
        self.assertEqual(defs["file_paths"].type, ("string[]",))

    def test_core_field_cannot_be_redeclared(self):
        with self.assertRaises(UsageError):
            load_field_defs({"fields": {"keywords": {"type": "string"}}})

    def test_unknown_type_expression_names_the_field(self):
        with self.assertRaises(UsageError) as ctx:
            load_field_defs({"fields": {"owners": {"type": "list<string>", "owner": "ui"}}})
        self.assertIn("owners", str(ctx.exception))
        self.assertIn("ui", str(ctx.exception))


class JsonSchemaTest(unittest.TestCase):
    def test_schema_shape(self):
        schema = to_json_schema(load_field_defs({}), ["active", "draft"])
        module = schema["properties"]["modules"]["additionalProperties"]
        self.assertEqual(module["properties"]["status"]["enum"], ["active", "draft"])
        self.assertIn("name", module["required"])
        child = module["properties"]["submodules"]["additionalProperties"]
        self.assertIn("keywords", child["properties"])
        self.assertIn("context_files", child["required"])
        self.assertIn("anyOf", module["properties"]["negative_keywords"])



class FieldDeclarationValidationTest(unittest.TestCase):  # every declaration is checked
    def assertFieldError(self, spec, *needles):
        with self.assertRaises(UsageError) as ctx:
            load_field_defs({"fields": {"x": spec}})
        for needle in ("'x'", *needles):
            self.assertIn(needle, str(ctx.exception))

    def test_type_is_required_and_typed(self):
        for spec in ({"owner": "ui"}, {"type": [], "owner": "ui"}, {"type": ["string", 5], "owner": "ui"}):
            with self.subTest(spec=spec):
                self.assertFieldError(spec, "owner ui", "type")

    def test_scope_and_required_values(self):
        self.assertFieldError({"type": "string", "scope": "child"}, "owner config", "scope")
        self.assertFieldError({"type": "string", "required": ["module", "all"]}, "required")

    def test_valid_declaration_with_every_key(self):
        defs = load_field_defs({"fields": {"x": {
            "type": ["string", "string[]"], "scope": ["module", "submodule"], "description": "d",
            "kind": "code_pointer", "used_by": ["show"], "ask_on_create": True, "sync_hint": "h",
            "deprecated": "", "required": "module", "owner": "ui"}}})
        self.assertEqual(defs["x"].type, ("string", "string[]"))
        self.assertEqual(defs["x"].required, ("module",))


if __name__ == "__main__":
    unittest.main()
