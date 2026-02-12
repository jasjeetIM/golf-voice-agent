from __future__ import annotations

from voice_gateway.app.main import _compute_twilio_signature, _is_twilio_signature_valid


def test_twilio_signature_validation_accepts_matching_signature() -> None:
    token = "auth-token"
    url = "https://example.com/twilio/inbound"
    params = [("CallSid", "CA123"), ("From", "+15550001")]
    signature = _compute_twilio_signature(token, url, params)

    assert _is_twilio_signature_valid(
        signature=signature,
        auth_token=token,
        candidate_urls=[url],
        params=params,
    )


def test_twilio_signature_validation_rejects_mismatch() -> None:
    token = "auth-token"
    url = "https://example.com/twilio/inbound"
    params = [("CallSid", "CA123")]
    signature = _compute_twilio_signature(token, url, params)

    assert not _is_twilio_signature_valid(
        signature=signature,
        auth_token="different-token",
        candidate_urls=[url],
        params=params,
    )
