import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
REGISTRY_PATH = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "china_platform_connectors.json"
)


def _registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_china_platform_writes_are_campaign_eligible_not_globally_frozen():
    registry = _registry()

    assert registry["registry_version"] == "1.1"
    assert "campaign grant" in registry["default_policy"]["write_api"]
    for platform in registry["platforms"]:
        assert platform["write_scopes_campaign_eligible"]
        assert "write_scopes_frozen" not in platform


def test_douyin_and_xiaohongshu_keep_full_operation_surfaces():
    platforms = {item["id"]: item for item in _registry()["platforms"]}
    douyin = platforms["douyin_ecommerce"]
    xiaohongshu = platforms["xiaohongshu"]

    for action in ("评论/回复", "点赞/关注", "私信", "账号操作"):
        assert action in douyin["write_scopes_campaign_eligible"]
    for action in ("内容发布/删除", "评论/回复", "点赞/收藏", "关注"):
        assert action in xiaohongshu["write_scopes_campaign_eligible"]
    assert xiaohongshu["status"] == "isolated_cli_installed_not_authenticated"
    assert xiaohongshu["additional_adapter_required"] == [
        "私信",
        "媒体下载",
        "直播",
    ]
