"""配置加载。

设计原则：
- 所有可调参数都以 dataclass 默认值兜底，config.ini 只做**覆盖**
- 配置文件缺失或缺字段不会导致崩溃，用默认值继续
- 只有 [llm] 的 base_url / api_key / model 是必需的（否则无法工作）

配置文件缺失时由 `ensure_config_file()` 生成一份完整模板。
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """配置文件缺失或关键字段不合法。"""


# ====================================================================== 读取工具
def _get(section: configparser.SectionProxy, key: str, default: Any) -> Any:
    """按默认值的类型读取并转换；失败时回退默认值，不抛异常。"""
    raw = section.get(key)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        return default

    try:
        if isinstance(default, bool):
            return raw.lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        return raw
    except (TypeError, ValueError):
        return default


# ====================================================================== LLM
@dataclass(frozen=True)
class LLMSettings:
    """LLM 连接参数。"""

    base_url: str
    api_key: str
    model: str
    timeout: float = 120.0

    def __repr__(self) -> str:  # 避免日志/异常里泄露密钥
        return f"LLMSettings(base_url={self.base_url!r}, model={self.model!r})"


# ====================================================================== Agent
@dataclass(frozen=True)
class AgentSettings:
    """Agent 运行时参数。"""

    max_tool_rounds: int = 199
    max_model_calls_per_round: int = 200
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


# ====================================================================== 上下文
@dataclass(frozen=True)
class ContextSettings:
    """上下文压缩与检索参数。"""

    warn_ratio: float = 0.70
    danger_ratio: float = 0.85
    default_window: int = 128 * 1024
    summary_target_tokens: int = 5000
    archive_dir: str = ".agents/context"
    max_content_chars: int = 200_000
    recall_max_snippets: int = 6
    recall_snippet_chars: int = 400
    recall_max_total_chars: int = 4000

    def __repr__(self) -> str:
        return f"ContextSettings(warn_ratio={self.warn_ratio}, window={self.default_window})"


# ====================================================================== 会话
@dataclass(frozen=True)
class SessionSettings:
    """会话持久化参数。"""

    dir: str = ".agents/sessions"
    autosave: bool = True
    agents_md: str = "AGENTS.md"

    def __repr__(self) -> str:
        return f"SessionSettings(dir={self.dir!r}, autosave={self.autosave})"


# ====================================================================== FS
@dataclass(frozen=True)
class FsSettings:
    """文件系统工具配置。"""

    max_read_chars: int = 20000
    max_list_entries: int = 500
    #: 允许访问的根目录（逗号或分号分隔）。为空表示不限制。
    allowed_roots: str = ""
    #: 覆盖已有文件、删除文件/目录是否要求显式确认
    require_confirm: bool = True
    #: 是否自动把当前工作目录加入允许范围
    include_cwd: bool = True

    @property
    def root_list(self) -> list[str]:
        raw = (self.allowed_roots or "").replace(";", ",")
        return [p.strip() for p in raw.split(",") if p.strip()]

    def __repr__(self) -> str:
        return (
            f"FsSettings(max_read_chars={self.max_read_chars}, "
            f"max_list_entries={self.max_list_entries}, "
            f"allowed_roots={self.root_list!r}, "
            f"require_confirm={self.require_confirm})"
        )


# ====================================================================== CLI
@dataclass(frozen=True)
class CliSettings:
    """本地命令执行配置。"""

    timeout: float = 15.0
    max_output_chars: int = 4000
    workdir: str | None = None

    def __repr__(self) -> str:
        return f"CliSettings(timeout={self.timeout}, max_output_chars={self.max_output_chars})"


# ====================================================================== Fetch
@dataclass(frozen=True)
class FetchSettings:
    """网页抓取配置。"""

    curl_path: str = "curl"
    timeout: float = 20.0
    max_chars: int = 12000
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __repr__(self) -> str:
        return f"FetchSettings(curl={self.curl_path!r}, timeout={self.timeout})"


# ====================================================================== Search
@dataclass(frozen=True)
class SearchSettings:
    """联网搜索配置。"""

    api_key: str = ""
    endpoint: str = "https://qianfan.baidubce.com/v2/ai_search/chat/completions"
    resource_id: str = "ai_search"
    search_source: str = "baidu_search_v2"
    top_k: int = 5
    timeout: float = 20.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def __repr__(self) -> str:
        return f"SearchSettings(configured={self.configured}, top_k={self.top_k})"


# ====================================================================== MCP
@dataclass(frozen=True)
class McpSettings:
    """MCP 客户端配置。"""

    filename: str = ".mcp.json"
    connect_timeout: float = 10.0
    call_timeout: float = 60.0
    prefix_mode: str = "auto"
    async_load: bool = True
    default_window: int = 128 * 1024

    def __repr__(self) -> str:
        return f"McpSettings(filename={self.filename!r}, async_load={self.async_load})"


# ====================================================================== UI
@dataclass(frozen=True)
class UISettings:
    """界面参数。"""

    typing_delay: float = 0.0
    sidebar_width: int = 38
    max_skill_desc: int = 56
    max_tool_desc: int = 60

    def __repr__(self) -> str:
        return f"UISettings(sidebar_width={self.sidebar_width})"


# ====================================================================== 聚合
@dataclass(frozen=True)
class AppConfig:
    """应用配置聚合。"""

    llm: LLMSettings
    agent: AgentSettings = field(default_factory=AgentSettings)
    context: ContextSettings = field(default_factory=ContextSettings)
    session: SessionSettings = field(default_factory=SessionSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    fetch: FetchSettings = field(default_factory=FetchSettings)
    cli: CliSettings = field(default_factory=CliSettings)
    fs: FsSettings = field(default_factory=FsSettings)
    mcp: McpSettings = field(default_factory=McpSettings)
    ui: UISettings = field(default_factory=UISettings)

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        """从 ini 文件加载。只有 [llm] 的关键字段是必需的。"""
        path = Path(path)
        if not path.is_file():
            raise ConfigError(f"找不到配置文件: {path}")

        parser = configparser.ConfigParser()
        if not parser.read(path, encoding="utf-8-sig"):
            raise ConfigError(f"配置文件读取失败: {path}")
        if not parser.has_section("llm"):
            raise ConfigError(f"配置文件缺少 [llm] 段: {path}")

        section = parser["llm"]
        missing = [k for k in ("base_url", "api_key", "model") if not (section.get(k) or "").strip()]
        if missing:
            raise ConfigError(f"配置文件缺少字段 {', '.join(missing)}: {path}")

        llm_defaults = {"timeout": 120.0}
        llm = LLMSettings(
            base_url=section["base_url"].strip(),
            api_key=section["api_key"].strip(),
            model=section["model"].strip(),
            timeout=_get(section, "timeout", llm_defaults["timeout"]),
        )

        return cls(
            llm=llm,
            agent=cls._load_agent(parser),
            context=cls._load_context(parser),
            session=cls._load_session(parser),
            search=cls._load_search(parser),
            fetch=cls._load_fetch(parser),
            cli=cls._load_cli(parser),
            fs=cls._load_fs(parser),
            mcp=cls._load_mcp(parser),
            ui=cls._load_ui(parser),
        )

    # ------------------------------------------------------------ 各段加载
    @staticmethod
    def _section(parser: configparser.ConfigParser, name: str):
        return parser[name] if parser.has_section(name) else None

    @classmethod
    def _fill(cls, parser, section_name: str, settings_cls):
        """按 dataclass 字段逐项读取，缺失的用默认值。"""
        defaults = settings_cls()
        section = cls._section(parser, section_name)
        values = {}
        for f in fields(settings_cls):
            default = getattr(defaults, f.name)
            values[f.name] = _get(section, f.name, default) if section else default
        return settings_cls(**values)

    @classmethod
    def _load_agent(cls, parser) -> AgentSettings:
        defaults = AgentSettings()
        section = cls._section(parser, "agent")
        if not section:
            return defaults
        return AgentSettings(
            max_tool_rounds=_get(section, "max_tool_rounds", defaults.max_tool_rounds),
            max_model_calls_per_round=_get(
                section, "max_model_calls_per_round", defaults.max_model_calls_per_round
            ),
            system_prompt=_get(section, "system_prompt", defaults.system_prompt),
        )

    @classmethod
    def _load_context(cls, parser) -> ContextSettings:
        return cls._fill(parser, "context", ContextSettings)

    @classmethod
    def _load_session(cls, parser) -> SessionSettings:
        return cls._fill(parser, "session", SessionSettings)

    @classmethod
    def _load_search(cls, parser) -> SearchSettings:
        defaults = SearchSettings()
        section = cls._section(parser, "search")
        if not section:
            return defaults
        return SearchSettings(
            api_key=_get(section, "baidu_qianfan_api_key", defaults.api_key)
            or _get(section, "api_key", defaults.api_key),
            endpoint=_get(section, "endpoint", defaults.endpoint),
            resource_id=_get(section, "resource_id", defaults.resource_id),
            search_source=_get(section, "search_source", defaults.search_source),
            top_k=_get(section, "top_k", defaults.top_k),
            timeout=_get(section, "timeout_seconds", defaults.timeout),
        )

    @classmethod
    def _load_fetch(cls, parser) -> FetchSettings:
        defaults = FetchSettings()
        section = cls._section(parser, "fetch")
        if not section:
            return defaults
        return FetchSettings(
            curl_path=_get(section, "curl_path", defaults.curl_path),
            timeout=_get(section, "timeout_seconds", defaults.timeout),
            max_chars=_get(section, "max_chars", defaults.max_chars),
            user_agent=_get(section, "user_agent", defaults.user_agent),
        )

    @classmethod
    def _load_cli(cls, parser) -> CliSettings:
        defaults = CliSettings()
        section = cls._section(parser, "cli")
        if not section:
            return defaults
        workdir = _get(section, "workdir", "") or None
        return CliSettings(
            timeout=_get(section, "timeout_seconds", defaults.timeout),
            max_output_chars=_get(section, "max_output_chars", defaults.max_output_chars),
            workdir=workdir,
        )

    @classmethod
    def _load_fs(cls, parser) -> FsSettings:
        return cls._fill(parser, "fs", FsSettings)

    @classmethod
    def _load_mcp(cls, parser) -> McpSettings:
        return cls._fill(parser, "mcp", McpSettings)

    @classmethod
    def _load_ui(cls, parser) -> UISettings:
        return cls._fill(parser, "ui", UISettings)


# ====================================================================== 模板
CONFIG_TEMPLATE = """\
# wAgent 配置文件
# 首次运行自动生成。请把 apikey 换成真实值后重新启动 wAgent。

[llm]
; 必需：OpenAI 兼容接口地址、密钥、模型名
base_url = https://api.deepseek.com/v1
api_key = sk-请替换为你的真实APIKey
model = deepseek-chat
; 单次请求超时（秒）
timeout = 120

[agent]
; 每轮最多允许几次「工具调用→再请求模型」
max_tool_rounds = 199
; 每轮调用模型的总次数上限（含最后一次生成回答）
max_model_calls_per_round = 200

[context]
; 上下文占用达到该比例时提示压缩
warn_ratio = 0.70
; 超过该比例显示危险色
danger_ratio = 0.85
; 无法识别模型上下文窗口时的默认值
default_window = 131072
; 压缩摘要的目标 token 数
summary_target_tokens = 5000
; 归档目录（相对项目根）
archive_dir = .agents/context
; 单条归档记录的最大保存长度
max_content_chars = 200000
; recallContext 返回的片段数上限
recall_max_snippets = 6
; 单个片段的字符数
recall_snippet_chars = 400
; 检索结果总长度上限
recall_max_total_chars = 4000

[session]
; 会话保存目录（相对项目根）
dir = .agents/sessions
; /new 时是否自动保存当前会话
autosave = true
; 项目指令文件名
agents_md = AGENTS.md

[search]
; 百度千帆智能搜索的 API Key，留空则 searchWeb 不可用
baidu_qianfan_api_key =
endpoint = https://qianfan.baidubce.com/v2/ai_search/chat/completions
resource_id = ai_search
search_source = baidu_search_v2
top_k = 5
timeout_seconds = 20

[fetch]
; 本地 curl 可执行文件名
curl_path = curl
timeout_seconds = 20
; 单页正文最大字符数
max_chars = 12000
; 留空使用内置 User-Agent
user_agent =

[cli]
; 命令执行超时（秒）
timeout_seconds = 15
; stdout / stderr 各自的最大字符数
max_output_chars = 4000
; 留空则使用当前工作目录
workdir =

[fs]
; readFile 单次返回的最大字符数
max_read_chars = 20000
; listDir 最多列出的条目数
max_list_entries = 500
; 允许访问的根目录，多个用逗号分隔。留空表示不限制。
; 建议显式限定，防止模型误操作范围外的文件。
; 例如：allowed_roots = D:/office, D:/projects
allowed_roots =
; 覆盖已有文件、删除操作是否要求显式确认
require_confirm = true
; 是否自动把当前工作目录加入允许范围
include_cwd = true

[mcp]
; MCP 服务器配置文件（相对项目根）
filename = .mcp.json
connect_timeout = 10
call_timeout = 60
; 工具名冲突时的前缀策略：auto / always / never
prefix_mode = auto
; 是否异步加载 MCP（先进入界面再连接）
async_load = true

[ui]
; 侧栏宽度（列）
sidebar_width = 38
; 技能描述最多显示多少字
max_skill_desc = 56
; 工具描述最多显示多少字
max_tool_desc = 60
"""


def ensure_config_file(path: str | Path) -> tuple[Path, bool]:
    """确保配置文件存在。

    返回 (路径, 是否新建)。新建时会写入完整模板（含 mock 值）。
    """
    path = Path(path)
    if path.is_file():
        return path, False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return path, True


MOCK_API_KEY = "sk-请替换为你的真实APIKey"


def is_mock_config(config: AppConfig) -> bool:
    """判断是否仍是模板里的占位值。"""
    return (
        not config.llm.api_key
        or config.llm.api_key.startswith("sk-请替换")
        or "你的" in config.llm.api_key
    )


__all__ = [
    "CONFIG_TEMPLATE",
    "MOCK_API_KEY",
    "AgentSettings",
    "AppConfig",
    "CliSettings",
    "ConfigError",
    "ContextSettings",
    "FetchSettings",
    "FsSettings",
    "LLMSettings",
    "McpSettings",
    "SearchSettings",
    "SessionSettings",
    "UISettings",
    "ensure_config_file",
    "is_mock_config",
]
