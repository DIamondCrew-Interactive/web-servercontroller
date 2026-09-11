"""Ephemeral test keys only. No production secrets or private-key fixtures on disk."""
import base64
import json
import time
import uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def keys():
    private = Ed25519PrivateKey.generate()
    pem = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    return private, {'test-key': pem}


def config(public):
    return {'origin': 'https://admin.example', 'staff_origin': 'https://staff.example', 'audience': 'servercontroller', 'redeem_secret': 's' * 43, 'verification_keys': public}


def claims(**changes):
    now = int(time.time())
    return {'iss': 'https://staff.example', 'aud': 'servercontroller', 'sub': '584274123622973440', 'iat': now, 'exp': now + 45, 'jti': str(uuid.uuid4()), 'state': 't' * 43, **changes}


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def sign(private, value, header=None, raw_claims=None):
    header = header if header is not None else {'alg': 'EdDSA', 'typ': 'JWT', 'kid': 'test-key'}
    body = b64(json.dumps(header, separators=(',', ':')).encode()) + '.' + b64(raw_claims if raw_claims is not None else json.dumps(value, separators=(',', ':')).encode())
    return body + '.' + b64(private.sign(body.encode('ascii')))


def envelope(private, value):
    return {'assertion': sign(private, value), 'token_type': 'DCI-SSO', 'expires_in': 45}
