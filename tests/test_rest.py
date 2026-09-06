from api.rest import decode_jwt_claims, extract_token

JWT = "eyJ0eXAiOiJKV1QiLCJhbGciOiJQUzI1NiJ9.eyJhdWQiOiJ1c2VyLWFwaSIsInN1YiI6ImFiYyJ9.c2ln"


def test_decode_claims():
    assert decode_jwt_claims(JWT) == {"aud": "user-api", "sub": "abc"}
    assert decode_jwt_claims("garbage") == {}


def test_extract_token_from_various_shapes():
    assert extract_token({"jwt": JWT}) == JWT
    assert extract_token({"accessToken": JWT, "refreshToken": "x"}) == JWT
    assert extract_token({"data": {"token": JWT}}) == JWT
    assert extract_token(JWT) == JWT
    assert extract_token({"token": "not-a-jwt"}) is None
