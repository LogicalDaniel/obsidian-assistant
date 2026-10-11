"""The system prompt for one model call.

Each section is produced by its own source. This module only joins the
non-empty ones, in a fixed order, so the prefix stays stable across a run.
"""

from __future__ import annotations

from skills.skill import Skill, catalog
from tools.registry import ToolRegistry


def system_prompt(skills: list[Skill], tools: ToolRegistry) -> str:
    sections = [tool_rules(), catalog(skills), deferred_catalog(tools)]
    return "\n\n".join(section for section in sections if section)


def tool_rules() -> str:
    """Resident-tool rules. Schemas stay in the tools field; this only separates easy-to-confuse uses."""
    return "\n".join(
        [
            "工具怎么选。",
            "- 笔记库路径用 read_note。工作区的 skills/ 和 sessions/.../tools/ 用 read_file。read_file 说不在工作区时，改用 read_note，不要停。",
            "- search_notes 的片段不能当答案。用该条的 path 和 line 调用 read_note。",
            "- 这一页写着数字在后文，才用更大的 offset 再读。不要问用户要不要继续。",
            "- 当前页写明数字在另一篇，或只存在于另一篇的表里，就打开那一篇再回答。问题点了两篇，两篇都要读完。",
            "- 插入和删除的行号按 read_note 正文计，空行也算。预览后文件变了、写入被拒绝时，不要重试同一次修改，告诉用户文件已变。",
            "- 工作区里的摘要和证据用 write_file。笔记库里的新笔记用 create_note。",
        ]
    )


def deferred_catalog(tools: ToolRegistry) -> str:
    items = tools.deferred()
    if not items:
        return ""
    lines = [
        "未加载的工具。要用时先调用 tool_describe，下一步才会出现参数说明。不要把它们直接放进 tool_calls。",
    ]
    for name, description in items:
        lines.append(f"- name: {name}")
        lines.append(f"  description: {description}")
    return "\n".join(lines)
