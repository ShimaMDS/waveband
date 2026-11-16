"""The release key file, locked with a passphrase."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import release_key  # noqa: E402

from wwmeter import signing  # noqa: E402

FAST = 2 ** 10  # scrypt's cost for the tests; the real file uses 2 ** 17


class ReleaseKeyTest(unittest.TestCase):
    def test_the_key_comes_back_with_the_right_passphrase(self):
        secret = signing.new_secret()
        text = release_key.lock(secret, "correct horse battery", n=FAST)
        self.assertEqual(release_key.unlock(text, "correct horse battery"), secret)

    def test_a_wrong_passphrase_gives_nothing(self):
        text = release_key.lock(signing.new_secret(), "correct horse battery", n=FAST)
        with self.assertRaises(release_key.Locked):
            release_key.unlock(text, "correct horse batterY")

    def test_the_file_holds_neither_the_key_nor_the_passphrase(self):
        secret = signing.new_secret()
        text = release_key.lock(secret, "correct horse battery", n=FAST)
        self.assertNotIn(secret.hex(), text)
        self.assertNotIn("correct horse battery", text)
        self.assertIn(signing.public_key(secret).hex(), text)  # the public half is no secret

    def test_two_lockings_of_one_key_differ(self):
        secret = signing.new_secret()
        self.assertNotEqual(release_key.lock(secret, "same passphrase!", n=FAST),
                            release_key.lock(secret, "same passphrase!", n=FAST))


if __name__ == "__main__":
    unittest.main()
