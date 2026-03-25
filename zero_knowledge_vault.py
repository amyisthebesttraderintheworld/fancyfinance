from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PBKDF2_SHA256 = "pbkdf2-sha256"
VAULT_VERSION = "zk-v1"
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 32
NONCE_BYTES = 12
KEY_BYTES = 32


class VaultError(Exception):
    pass


class InvalidPassphraseError(VaultError):
    pass


class ZeroKnowledgeVault:
    def _derive_key(self, passphrase: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_BYTES,
            salt=salt,
            iterations=iterations,
        )
        return kdf.derive(passphrase.encode("utf-8"))

    def encrypt_credentials(
        self,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        exchange: str,
        associated_data: Optional[bytes] = None,
        iterations: int = PBKDF2_ITERATIONS,
    ) -> Dict[str, Any]:
        if not passphrase or not passphrase.strip():
            raise ValueError("passphrase is required")

        plaintext = json.dumps(
            {
                "api_key": api_key,
                "api_secret": api_secret,
            },
            separators=(",", ":"),
        ).encode("utf-8")

        salt = os.urandom(SALT_BYTES)
        nonce = os.urandom(NONCE_BYTES)
        key = self._derive_key(passphrase, salt, iterations)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)

        return {
            "version": VAULT_VERSION,
            "exchange": exchange,
            "encrypted_blob": ciphertext.hex(),
            "salt": salt.hex(),
            "nonce": nonce.hex(),
            "kdf": PBKDF2_SHA256,
            "kdf_iterations": iterations,
        }

    def decrypt_credentials(
        self,
        vault_record: Dict[str, Any],
        *,
        passphrase: str,
        associated_data: Optional[bytes] = None,
    ) -> Dict[str, str]:
        if not passphrase or not passphrase.strip():
            raise InvalidPassphraseError("passphrase is required")

        iterations = int(vault_record.get("kdf_iterations") or PBKDF2_ITERATIONS)
        salt = bytes.fromhex(vault_record["salt"])
        nonce = bytes.fromhex(vault_record["nonce"])
        ciphertext = bytes.fromhex(vault_record["encrypted_blob"])
        key = self._derive_key(passphrase, salt, iterations)

        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data)
        except InvalidTag as exc:
            raise InvalidPassphraseError("vault decryption failed") from exc

        payload = json.loads(plaintext.decode("utf-8"))
        return {
            "api_key": payload["api_key"],
            "api_secret": payload["api_secret"],
        }
