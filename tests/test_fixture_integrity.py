from conftest import (
    FIXTURES,
    LOBBY_FIXTURE_SHA256,
    SAVE_FIXTURE_SHA256,
    sha256_file,
)


def test_user_owned_fixtures_keep_their_original_hashes() -> None:
    assert sha256_file(FIXTURES / "save.save") == SAVE_FIXTURE_SHA256
    assert sha256_file(FIXTURES / "lobby.save") == LOBBY_FIXTURE_SHA256
