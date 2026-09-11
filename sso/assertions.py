"""Strict Staff Ed25519 JWT verification. Keys come only from local configuration."""
import base64
import json
import re
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

KID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
JTI = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON member')
            result[key] = value
        return result
    def invalid(_value):
        raise ValueError('Invalid JSON number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def decode(segment):
    if not isinstance(segment, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', segment):
        raise ValueError('Invalid JWT encoding')
    raw = base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))
    if base64.urlsafe_b64encode(raw).decode().rstrip('=') != segment:
        raise ValueError('Noncanonical JWT encoding')
    return raw


def load_keys(configured):
    if not isinstance(configured, dict) or not 1 <= len(configured) <= 8:
        raise ValueError('Configure trusted Staff public verification keys')
    result = {}
    for kid, pem in configured.items():
        if not isinstance(kid, str) or not KID.fullmatch(kid) or not isinstance(pem, str) or len(pem) > 1024:
            raise ValueError('Invalid verification key configuration')
        key = load_pem_public_key(pem.encode('ascii'))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError('An Ed25519 public key is required')
        result[kid] = key
    return result


def verify(assertion, config, state, now=None):
    if not isinstance(assertion, str) or len(assertion) > 4096 or assertion.count('.') != 2:
        raise ValueError('Missing signed Staff assertion')
    header64, claims64, signature64 = assertion.split('.')
    header = strict_json(decode(header64))
    if not isinstance(header, dict) or set(header) != {'alg', 'typ', 'kid'} or header.get('alg') != 'EdDSA' or header.get('typ') != 'JWT':
        raise ValueError('Unsupported JWT header')
    kid = header.get('kid')
    if not isinstance(kid, str) or not KID.fullmatch(kid):
        raise ValueError('Invalid JWT key ID')
    key = load_keys(config['verification_keys']).get(kid)
    if key is None:
        raise ValueError('Unknown Staff signing key')
    signature = decode(signature64)
    if len(signature) != 64:
        raise ValueError('Invalid Ed25519 signature size')
    try:
        key.verify(signature, (header64 + '.' + claims64).encode('ascii'))
    except InvalidSignature:
        raise ValueError('Invalid Staff signature') from None
    claims = strict_json(decode(claims64))
    if not isinstance(claims, dict) or set(claims) != {'iss', 'aud', 'sub', 'iat', 'exp', 'jti', 'state'}:
        raise ValueError('Unexpected Staff claims')
    if claims['iss'] != config['staff_origin'] or claims['aud'] != 'servercontroller':
        raise ValueError('Wrong Staff issuer or audience')
    if not isinstance(state, str) or not TOKEN.fullmatch(state) or claims['state'] != state:
        raise ValueError('Wrong browser state')
    if not isinstance(claims['sub'], str) or not re.fullmatch(r'[0-9]{17,20}', claims['sub']):
        raise ValueError('Invalid canonical identity')
    if not isinstance(claims['jti'], str) or not JTI.fullmatch(claims['jti']):
        raise ValueError('Invalid Staff assertion ID')
    issued, expires = claims['iat'], claims['exp']
    current = time.time() if now is None else now
    if type(issued) is not int or type(expires) is not int or not 0 < expires - issued <= 45 or issued > current + 5 or expires <= current:
        raise ValueError('Expired or invalid Staff assertion lifetime')
    return claims
