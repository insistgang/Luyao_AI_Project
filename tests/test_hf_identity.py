import unittest

from scripts.hf_identity import hf_space_url, resolve_space_id


class FakeHfApi:
    def whoami(self):
        return {"name": "Awu-Owner"}


class HuggingFaceIdentityTests(unittest.TestCase):
    def test_resolves_owner_from_token_identity(self) -> None:
        space_id = resolve_space_id(FakeHfApi())
        self.assertEqual(space_id, "Awu-Owner/Luyao_AI_Project")
        self.assertEqual(
            hf_space_url(space_id),
            "https://awu-owner-luyao-ai-project.hf.space",
        )

    def test_explicit_space_id_does_not_call_whoami(self) -> None:
        class NoNetworkApi:
            def whoami(self):
                raise AssertionError("whoami should not run")

        self.assertEqual(
            resolve_space_id(NoNetworkApi(), "team/luyao"),
            "team/luyao",
        )

    def test_rejects_invalid_space_identifier(self) -> None:
        with self.assertRaises(ValueError):
            resolve_space_id(FakeHfApi(), "owner/not/a/space")


if __name__ == "__main__":
    unittest.main()
