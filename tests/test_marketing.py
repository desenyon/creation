"""Marketing integration tests."""

from creation.integrations import marketing as mkt


def test_build_launch_email_html_includes_links():
    html = mkt.build_launch_email_html(
        product_name="SyncCLI",
        tagline="Sync everything",
        idea="Add OAuth",
        deploy_url="https://sync.vercel.app",
        github_url="https://github.com/u/r",
    )
    assert "SyncCLI" in html
    assert "https://sync.vercel.app" in html


def test_build_launch_social_post():
    post = mkt.build_launch_social_post(
        product_name="SyncCLI",
        tagline="Sync everything",
        idea="Add OAuth",
        deploy_url="https://sync.vercel.app",
    )
    assert "SyncCLI" in post
    assert "https://sync.vercel.app" in post


def test_parse_platforms():
    assert mkt._parse_platforms("twitter, linkedin, x") == ["twitter", "linkedin"]
    assert mkt._parse_platforms("all") == ["all"]


def test_launch_marketing_demo():
    result = mkt.launch_marketing(demo=True, social_post="hello")
    assert result.success
    assert "social" in result.channels


def test_launch_marketing_requires_config():
    result = mkt.launch_marketing(social_post="hello")
    assert not result.success
    assert "not configured" in result.message.lower()


def test_post_ayrshare_mock():
    result = mkt._post_ayrshare()
    assert result.success
    assert "social" in result.channels
