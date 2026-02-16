"""LemonSqueezy license management for Pro features."""

import hashlib
import hmac
import json
import os
import platform
import threading
import time
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass
from pathlib import Path


# Replace with your actual LemonSqueezy checkout URL
PURCHASE_URL = "https://yourstore.lemonsqueezy.com/buy/your-product-id"

_API_BASE = "https://api.lemonsqueezy.com/v1/licenses"

# How many seconds offline grace lasts since last successful server validation
_OFFLINE_GRACE_SECONDS = 7 * 24 * 3600  # 7 days

# Salt used for HMAC signing the license cache — change this to your own value
_SIGNING_SALT = b"SpectrumAnalyzer_v1_license_signing_key_change_me"


def _license_path() -> Path:
    return Path(os.path.dirname(os.path.abspath(__file__))) / "license.json"


def _machine_fingerprint() -> str:
    """Derive a stable fingerprint from machine-specific attributes."""
    parts = [
        platform.node(),
        platform.machine(),
        platform.processor(),
        os.name,
    ]
    raw = "|".join(parts).encode()
    return hashlib.sha256(raw).hexdigest()


def _compute_signature(license_key: str, instance_id: str, validated_at: float) -> str:
    """HMAC-sign the license data so local edits are detected."""
    payload = f"{license_key}:{instance_id}:{validated_at:.0f}:{_machine_fingerprint()}"
    return hmac.new(_SIGNING_SALT, payload.encode(), hashlib.sha256).hexdigest()


def _verify_signature(license_key: str, instance_id: str, validated_at: float,
                      signature: str) -> bool:
    expected = _compute_signature(license_key, instance_id, validated_at)
    return hmac.compare_digest(expected, signature)


@dataclass
class _LicenseData:
    license_key: str = ""
    instance_id: str = ""
    validated_at: float = 0.0   # unix timestamp of last successful server validation
    signature: str = ""         # HMAC of the above fields


class LicenseManager:
    def __init__(self):
        self._data = _LicenseData()
        self._is_pro: bool = False
        self._status_message: str = ""
        self._busy: bool = False
        self._lock = threading.Lock()
        self._load()

    @property
    def is_pro(self) -> bool:
        return self._is_pro

    @property
    def status_message(self) -> str:
        return self._status_message

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def has_key(self) -> bool:
        return bool(self._data.license_key)

    def validate_on_startup(self):
        """Validate saved license in background thread. Call once at startup."""
        if not self._data.license_key or not self._data.instance_id:
            return
        # Check signature before even attempting validation
        if not self._verify_local():
            self._data = _LicenseData()
            self._delete_file()
            return
        self._run_in_background(self._do_validate)

    def activate(self, license_key: str):
        """Activate a license key in background thread."""
        if self._busy:
            return
        self._data.license_key = license_key.strip()
        self._run_in_background(self._do_activate)

    def deactivate(self):
        """Deactivate the current license in background thread."""
        if self._busy or not self._data.license_key:
            return
        self._run_in_background(self._do_deactivate)

    def _verify_local(self) -> bool:
        """Check that the saved license data hasn't been tampered with."""
        if not self._data.signature:
            return False
        return _verify_signature(
            self._data.license_key,
            self._data.instance_id,
            self._data.validated_at,
            self._data.signature,
        )

    def _run_in_background(self, target):
        self._busy = True
        self._status_message = "Checking..."
        t = threading.Thread(target=target, daemon=True)
        t.start()

    def _do_activate(self):
        try:
            instance_name = platform.node() or "SpectrumAnalyzer"
            data = urllib.parse.urlencode({
                "license_key": self._data.license_key,
                "instance_name": instance_name,
            }).encode()
            req = urllib.request.Request(
                f"{_API_BASE}/activate",
                data=data,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())

            if result.get("activated"):
                instance = result.get("instance", {})
                self._data.instance_id = instance.get("id", "")
                self._data.validated_at = time.time()
                self._data.signature = _compute_signature(
                    self._data.license_key,
                    self._data.instance_id,
                    self._data.validated_at,
                )
                self._save()
                with self._lock:
                    self._is_pro = True
                    self._status_message = "License activated!"
            else:
                error = result.get("error", "Activation failed")
                with self._lock:
                    self._is_pro = False
                    self._status_message = f"Error: {error}"
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            try:
                err_data = json.loads(body)
                msg = err_data.get("error", str(e))
            except Exception:
                msg = str(e)
            with self._lock:
                self._is_pro = False
                self._status_message = f"Error: {msg}"
        except Exception as e:
            with self._lock:
                self._is_pro = False
                self._status_message = f"Error: {e}"
        finally:
            self._busy = False

    def _do_validate(self):
        try:
            data = urllib.parse.urlencode({
                "license_key": self._data.license_key,
                "instance_id": self._data.instance_id,
            }).encode()
            req = urllib.request.Request(
                f"{_API_BASE}/validate",
                data=data,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())

            if result.get("valid"):
                # Refresh the validation timestamp and re-sign
                self._data.validated_at = time.time()
                self._data.signature = _compute_signature(
                    self._data.license_key,
                    self._data.instance_id,
                    self._data.validated_at,
                )
                self._save()
                with self._lock:
                    self._is_pro = True
                    self._status_message = "License valid"
            else:
                error = result.get("error", "Invalid license")
                self._data = _LicenseData()
                self._delete_file()
                with self._lock:
                    self._is_pro = False
                    self._status_message = f"License invalid: {error}"
        except Exception:
            # Network error — allow offline grace if last validation was recent enough
            age = time.time() - self._data.validated_at
            if self._data.validated_at > 0 and age < _OFFLINE_GRACE_SECONDS:
                days_left = int((_OFFLINE_GRACE_SECONDS - age) / 86400)
                with self._lock:
                    self._is_pro = True
                    self._status_message = f"License (offline, {days_left}d grace)"
            else:
                with self._lock:
                    self._is_pro = False
                    self._status_message = "License expired (offline too long)"
        finally:
            self._busy = False

    def _do_deactivate(self):
        try:
            data = urllib.parse.urlencode({
                "license_key": self._data.license_key,
                "instance_id": self._data.instance_id,
            }).encode()
            req = urllib.request.Request(
                f"{_API_BASE}/deactivate",
                data=data,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())

            if result.get("deactivated"):
                self._data = _LicenseData()
                self._delete_file()
                with self._lock:
                    self._is_pro = False
                    self._status_message = "License deactivated"
            else:
                error = result.get("error", "Deactivation failed")
                with self._lock:
                    self._status_message = f"Error: {error}"
        except Exception as e:
            with self._lock:
                self._status_message = f"Error: {e}"
        finally:
            self._busy = False

    def _save(self):
        try:
            with open(_license_path(), "w") as fp:
                json.dump({
                    "license_key": self._data.license_key,
                    "instance_id": self._data.instance_id,
                    "validated_at": self._data.validated_at,
                    "signature": self._data.signature,
                }, fp, indent=2)
        except Exception as e:
            print(f"Failed to save license: {e}")

    def _load(self):
        path = _license_path()
        if not path.exists():
            return
        try:
            with open(path, "r") as fp:
                data = json.load(fp)
            self._data.license_key = data.get("license_key", "")
            self._data.instance_id = data.get("instance_id", "")
            self._data.validated_at = data.get("validated_at", 0.0)
            self._data.signature = data.get("signature", "")
        except Exception as e:
            print(f"Failed to load license: {e}")

    def _delete_file(self):
        try:
            path = _license_path()
            if path.exists():
                path.unlink()
        except Exception:
            pass
