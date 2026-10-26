"""配置加载。

配置只属于 core：UI 层不应直接读配置文件，而是通过 AppConfig 使用。
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """配置文件缺失或字段不合法。"""


@dataclass(frozen=True)
class LLMSettings:
    """LLM 连接参数。"""

    base_url: str
    api_key: str
    model: str

    def __repr__(self) -> str:  # 避免日志/异常里泄露密钥
        return f"LLMSettings(base_url={self.base_url!r}, model={self.model!r})"


@dataclass(frozen=True)
class AgentSettings:
    """Agent 运行时参数。"""

    max_tool_rounds: int = 5
    system_prompt: str = (
        "你是一个可以调用工具的助手。"
        "当用户询问当前日期、时间、今天是几号或现在几点时，"
        "必须调用 getDate 工具获取当前电脑的日期和时间，不要自行猜测。"
        "当用户询问时事新闻、近期动态、实时数据，"
        "或问题超出你的知识范围、需要最新信息时，"
        "必须调用 searchWeb 工具联网搜索，不要凭记忆编造。"
        "引用搜索结果时请说明信息来源。"
        "当已经拿到某个网址、需要阅读全文或了解更多细节时，"
        "必须调用 fetchWeb 工具获取该网页正文，不要仅凭标题猜测内容。"
        "当需要查看本地文件、目录、运行脚本或查询系统信息时，"
        "调用 RunCli 工具执行本地命令，并根据返回的 stdout、stderr 和退出码判断结果；"
        "退出码非 0 时请把 stderr 中的关键错误告知用户。"
        "处理本地文件时优先使用专用工具：getCwd 查看工作目录、listDir 列目录、"
        "getFileType 判断类型、readFile 读内容、createFile 新建、editFile 修改、"
        "createDir 建目录、deleteDir / deleteFile 删除。"
        "readFile 与 editFile 只支持纯文本，二进制文件请改用 RunCli。"
        "删除操作不可恢复，执行前请确认路径正确，并向用户复述将被删除的内容。"
        "如果工具返回错误信息，请如实告知用户发生了什么问题，不要假装搜索成功。"
    )


@dataclass(frozen=True)
class FsSettings:
    """文件系统工具配置（getCwd / listDir / readFile …）。

    教学用途：不限制访问目录，路径以运行 Agent 的用户权限为准。
    """

    # readFile 单次返回的最大字符数
    max_read_chars: int = 20000
    # listDir 最多列出的条目数
    max_list_entries: int = 500

    def __repr__(self) -> str:
        return (
            f"FsSettings(max_read_chars={self.max_read_chars}, "
            f"max_list_entries={self.max_list_entries})"
        )


@dataclass(frozen=True)
class CliSettings:
    """本地命令执行配置（RunCli 工具）。

    教学用途：不设白名单/黑名单，命令以运行 Agent 的当前用户权限执行。
    """

    timeout: float = 15.0
    # 单次输出（stdout / stderr 各自）最大字符数，避免海量终端输出撑爆上下文
    max_output_chars: int = 4000
    # 相对路径的基准目录；None 表示继承 Agent 进程的工作目录
    workdir: str | None = None

    def __repr__(self) -> str:
        return f"CliSettings(timeout={self.timeout}, max_output_chars={self.max_output_chars})"


@dataclass(frozen=True)
class FetchSettings:
    """网页抓取配置（fetchWeb 工具）。

    不依赖 API Key，因此默认即可用；字段留出以便调整超时与体积上限。
    """

    curl_path: str = "curl"
    timeout: float = 20.0
    # 正文最大字符数，避免单页撑爆上下文
    max_chars: int = 12000
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __repr__(self) -> str:
        return f"FetchSettings(curl={self.curl_path!r}, timeout={self.timeout}, max_chars={self.max_chars})"


@dataclass(frozen=True)
class SearchSettings:
    """联网搜索配置。

    api_key 为空表示「未配置」——不视为启动错误，
    而是让工具在调用时向模型返回清晰的配置提示。
    """

    api_key: str = ""
    endpoint: str = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"
    resource_id: str = "ai_search"
    search_source: str = "baidu_search_v2"
    top_k: int = 5
    timeout: float = 20.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def __repr__(self) -> str:  # 避免密钥进入日志
        return f"SearchSettings(configured={self.configured}, top_k={self.top_k})"


@dataclass(frozen=True)
class AppConfig:
    """应用配置聚合。"""

    llm: LLMSettings
    agent: AgentSettings
    search: SearchSettings = field(default_factory=SearchSettings)
    fetch: FetchSettings = field(default_factory=FetchSettings)
    cli: CliSettings = field(default_factory=CliSettings)
    fs: FsSettings = field(default_factory=FsSettings)

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        """从 ini 文件加载。找不到或字段缺失时抛 ConfigError。"""
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"找不到配置文件: {path}")

        parser = configparser.ConfigParser()
        if not parser.read(path, encoding="utf-8"):
            raise ConfigError(f"配置文件读取失败: {path}")
        if not parser.has_section("llm"):
            raise ConfigError(f"配置文件缺少 [llm] 段: {path}")

        section = parser["llm"]
        missing = [k for k in ("base_url", "api_key", "model") if not section.get(k)]
        if missing:
            raise ConfigError(f"配置文件缺少字段 {', '.join(missing)}: {path}")

        return cls(
            llm=LLMSettings(
                base_url=section["base_url"].strip(),
                api_key=section["api_key"].strip(),
                model=section["model"].strip(),
            ),
            agent=AgentSettings(),
            search=cls._load_search(parser),
            fetch=cls._load_fetch(parser),
            cli=cls._load_cli(parser),
            fs=cls._load_fs(parser),
        )

    @staticmethod
    def _load_search(parser: configparser.ConfigParser) -> SearchSettings:
        """读取可选的 [search] 段。缺失时返回未配置状态，不阻断启动。"""
        if not parser.has_section("search"):
            return SearchSettings()

        s = parser["search"]
        defaults = SearchSettings()

        def _int(key: str, fallback: int) -> int:
            raw = (s.get(key) or "").strip()
            if not raw:
                return fallback
            try:
                return int(raw)
            except ValueError:
                return fallback

        return SearchSettings(
            api_key=(s.get("baidu_qianfan_api_key") or "").strip(),
            endpoint=(s.get("endpoint") or "").strip() or defaults.endpoint,
            resource_id=(s.get("resource_id") or "").strip() or defaults.resource_id,
            search_source=(s.get("search_source") or "").strip() or defaults.search_source,
            top_k=_int("top_k", defaults.top_k),
            timeout=float(_int("timeout_seconds", int(defaults.timeout))),
        )

    @staticmethod
    def _load_fetch(parser: configparser.ConfigParser) -> FetchSettings:
        """读取可选的 [fetch] 段；缺失则使用默认值。"""
        if not parser.has_section("fetch"):
            return FetchSettings()

        s = parser["fetch"]
        defaults = FetchSettings()

        def _num(key: str, fallback: float, cast=float):
            raw = (s.get(key) or "").strip()
            if not raw:
                return fallback
            try:
                return cast(raw)
            except ValueError:
                return fallback

        return FetchSettings(
            curl_path=(s.get("curl_path") or "").strip() or defaults.curl_path,
            timeout=_num("timeout_seconds", defaults.timeout),
            max_chars=_num("max_chars", defaults.max_chars, int),
        )

    @staticmethod
    def _load_cli(parser: configparser.ConfigParser) -> CliSettings:
        """读取可选的 [cli] 段；缺失则使用默认值。"""
        if not parser.has_section("cli"):
            return CliSettings()

        s = parser["cli"]
        defaults = CliSettings()

        def _num(key: str, fallback, cast=float):
            raw = (s.get(key) or "").strip()
            if not raw:
                return fallback
            try:
                return cast(raw)
            except ValueError:
                return fallback

        workdir = (s.get("workdir") or "").strip()
        return CliSettings(
            timeout=_num("timeout_seconds", defaults.timeout),
            max_output_chars=_num("max_output_chars", defaults.max_output_chars, int),
            workdir=workdir or None,
        )

    @staticmethod
    def _load_fs(parser: configparser.ConfigParser) -> FsSettings:
        """读取可选的 [fs] 段；缺失则使用默认值。"""
        if not parser.has_section("fs"):
            return FsSettings()

        s = parser["fs"]
        defaults = FsSettings()

        def _int(key: str, fallback: int) -> int:
            raw = (s.get(key) or "").strip()
            if not raw:
                return fallback
            try:
                value = int(raw)
                return value if value > 0 else fallback
            except ValueError:
                return fallback

        return FsSettings(
            max_read_chars=_int("max_read_chars", defaults.max_read_chars),
            max_list_entries=_int("max_list_entries", defaults.max_list_entries),
        )
