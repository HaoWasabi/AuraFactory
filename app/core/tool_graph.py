"""Tool Graph — NetworkX-based dependency graph for top-k tool retrieval.

Builds a directed graph from tools_spec.yaml where:
  - Nodes: tools, params, contexts, guild_features
  - Edges: requires_feature, needs_data_from, often_preceded_by,
            often_followed_by, inverse_of, should_verify_first

Retrieval flow:
  1. User request → keyword/embedding match → candidate tools
  2. Graph expansion → pull related tools (dependencies, prerequisites)
  3. Return top-k tools with their schemas + dependency info
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from app.core.spec_loader import SpecRegistry, ToolSpec

logger = logging.getLogger(__name__)


class ToolGraph:
    """In-memory tool dependency graph for intelligent retrieval.

    Phase 1: NetworkX (in-process, <5ms queries)
    Phase 2: AWS Neptune (distributed, persistent)
    """

    def __init__(self, registry: SpecRegistry) -> None:
        self._registry = registry
        self._graph = nx.DiGraph()
        self._tool_descriptions: Dict[str, str] = {}
        self._build_graph()

    def _build_graph(self) -> None:
        """Construct graph from spec registry."""
        tools = self._registry.get_all_tools()

        # Add tool nodes
        for tool_name, tool_spec in tools.items():
            self._graph.add_node(
                tool_name,
                node_type="tool",
                module=tool_spec.module,
                action=tool_spec.action,
                description=tool_spec.description,
                risk_level=tool_spec.risk_level,
                permissions=tool_spec.required_permissions,
            )
            self._tool_descriptions[tool_name] = tool_spec.description

            # Add context nodes and edges
            for ctx in tool_spec.get_context_keys():
                ctx_node = f"{tool_name}[{ctx}]"
                self._graph.add_node(ctx_node, node_type="context", parent_tool=tool_name)
                self._graph.add_edge(tool_name, ctx_node, relation="has_context")

            # Add tool-level graph edges
            for edge in tool_spec.graph_edges:
                target = edge.get("target", "")
                relation = edge.get("relation", "related_to")
                feature = edge.get("feature")

                if feature:
                    # Feature requirement edge
                    feat_node = f"FEATURE:{feature}"
                    if not self._graph.has_node(feat_node):
                        self._graph.add_node(feat_node, node_type="guild_feature")
                    self._graph.add_edge(tool_name, feat_node, relation="requires_feature")
                elif target.startswith("discord."):
                    # Tool-to-tool relationship
                    self._graph.add_edge(tool_name, target, relation=relation)

        # Add global edges
        for edge in self._registry.get_global_edges():
            from_node = edge.get("from", "")
            to_node = edge.get("to", "")
            relation = edge.get("relation", "related_to")

            # Handle context-specific edges like "discord.channels.create[stage]"
            if "[" in from_node:
                base_tool = from_node.split("[")[0]
                if not self._graph.has_node(from_node):
                    self._graph.add_node(from_node, node_type="context", parent_tool=base_tool)

            if to_node.startswith("COMMUNITY") or to_node.isupper():
                feat_node = f"FEATURE:{to_node}"
                if not self._graph.has_node(feat_node):
                    self._graph.add_node(feat_node, node_type="guild_feature")
                to_node = feat_node

            if self._graph.has_node(from_node) or "[" in from_node:
                self._graph.add_edge(from_node, to_node, relation=relation)

        logger.info(
            "ToolGraph built: %d nodes, %d edges",
            self._graph.number_of_nodes(),
            self._graph.number_of_edges(),
        )

    # ------------------------------------------------------------------
    # Top-K Retrieval
    # ------------------------------------------------------------------

    def retrieve_tools(
        self,
        query: str,
        k: int = 5,
        expand: bool = True,
    ) -> List[Dict[str, Any]]:
        """Retrieve top-k relevant tools for a user query.

        Strategy:
          1. Keyword match on tool descriptions + names
          2. Score and rank
          3. Optionally expand via graph neighbors (prerequisites, related)

        Args:
            query: User's natural language request.
            k: Maximum tools to return.
            expand: Whether to expand via graph relationships.

        Returns:
            List of dicts with tool info + schema + dependency context.
        """
        # Step 1: Score all tools by keyword relevance
        scores = self._keyword_score(query)

        # Step 2: Get top candidates
        sorted_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        candidates = [name for name, score in sorted_tools if score > 0][:k * 2]

        # Step 3: Expand via graph
        if expand and candidates:
            expanded = self._expand_candidates(candidates, k)
        else:
            expanded = candidates[:k]

        # Step 4: Build result with schemas and context
        results = []
        seen = set()
        for tool_name in expanded:
            if tool_name in seen or not tool_name.startswith("discord."):
                continue
            seen.add(tool_name)

            tool_spec = self._registry.get_tool(tool_name)
            if tool_spec is None:
                continue

            result = {
                "name": tool_name,
                "description": tool_spec.description,
                "risk_level": tool_spec.risk_level,
                "schema": self._registry.generate_tool_definition(tool_name),
                "prerequisites": self._get_prerequisites(tool_name),
                "constraints": tool_spec.constraints,
            }
            results.append(result)

            if len(results) >= k:
                break

        return results

    def _keyword_score(self, query: str) -> Dict[str, float]:
        """Simple keyword scoring — matches on tool name, description, module."""
        query_lower = query.lower()
        tokens = query_lower.split()
        scores: Dict[str, float] = {}

        # Keyword mapping for common intents
        intent_map = {
            "create": ["create", "tạo", "make", "new", "add", "setup"],
            "delete": ["delete", "xóa", "remove", "destroy"],
            "edit": ["edit", "sửa", "modify", "change", "update", "rename", "set"],
            "list": ["list", "show", "get", "xem", "hiển thị", "info", "query"],
            "assign": ["assign", "gán", "give", "grant"],
            "remove": ["remove", "bỏ", "revoke", "unassign"],
            "ban": ["ban", "cấm", "block"],
            "kick": ["kick", "đuổi"],
            "mute": ["mute", "tắt tiếng"],
            "timeout": ["timeout", "tạm khóa"],
            "clone": ["clone", "copy", "sao chép", "duplicate"],
            "move": ["move", "di chuyển"],
            "archive": ["archive", "lưu trữ"],
            "backup": ["backup", "sao lưu", "export", "import", "restore"],
        }

        # Module keyword mapping
        module_map = {
            "channels": ["channel", "kênh", "text", "voice", "stage", "forum"],
            "categories": ["category", "danh mục", "mục", "nhóm kênh"],
            "roles": ["role", "vai trò", "quyền", "permission"],
            "members": ["member", "thành viên", "user", "người dùng"],
            "guild": ["server", "guild", "máy chủ"],
            "webhooks": ["webhook"],
            "threads": ["thread", "luồng"],
            "invites": ["invite", "lời mời", "link"],
            "automod": ["automod", "tự động", "filter", "spam", "moderation"],
            "onboarding": ["welcome", "chào mừng", "onboard", "dm"],
            "events": ["event", "sự kiện", "scheduled", "lịch"],
            "emojis": ["emoji", "biểu tượng"],
            "stickers": ["sticker", "nhãn dán"],
            "soundboard": ["sound", "âm thanh", "soundboard"],
            "backup": ["backup", "sao lưu", "restore", "export", "import"],
            "features": ["feature", "tính năng", "community", "poll", "verify"],
            "templates": ["template", "mẫu"],
            "audit": ["audit", "log", "nhật ký"],
            "safety": ["safety", "content filter", "mfa", "2fa"],
            "community": ["community", "cộng đồng"],
        }

        for tool_name, desc in self._tool_descriptions.items():
            score = 0.0
            tool_lower = tool_name.lower()
            desc_lower = desc.lower()

            # Direct token match in description
            for token in tokens:
                if token in desc_lower:
                    score += 2.0
                if token in tool_lower:
                    score += 3.0

            # Intent matching
            tool_action = tool_name.split(".")[-1] if "." in tool_name else ""
            for action, keywords in intent_map.items():
                if any(kw in query_lower for kw in keywords):
                    if action == tool_action or action in tool_action:
                        score += 5.0

            # Module matching
            tool_module = tool_name.split(".")[1] if "." in tool_name else ""
            module_keywords = module_map.get(tool_module, [])
            for kw in module_keywords:
                if kw in query_lower:
                    score += 4.0
                    break

            scores[tool_name] = score

        return scores

    def _expand_candidates(
        self,
        candidates: List[str],
        k: int,
    ) -> List[str]:
        """Expand candidate set using graph relationships.

        Adds prerequisites and closely-related tools.
        """
        expanded = list(candidates)
        added: Set[str] = set(candidates)

        for tool_name in candidates[:k]:
            if not self._graph.has_node(tool_name):
                continue

            # Check predecessors (tools this one needs data from)
            for pred in self._graph.predecessors(tool_name):
                if pred.startswith("discord.") and pred not in added:
                    edge_data = self._graph.get_edge_data(pred, tool_name) or {}
                    rel = edge_data.get("relation", "")
                    if rel in ("needs_data_from", "often_preceded_by", "should_verify_first"):
                        expanded.append(pred)
                        added.add(pred)

            # Check successors (tools that should follow)
            for succ in self._graph.successors(tool_name):
                if succ.startswith("discord.") and succ not in added:
                    edge_data = self._graph.get_edge_data(tool_name, succ) or {}
                    rel = edge_data.get("relation", "")
                    if rel in ("often_followed_by", "inverse_of"):
                        expanded.append(succ)
                        added.add(succ)

        return expanded

    def _get_prerequisites(self, tool_name: str) -> List[str]:
        """Get prerequisite tools (things that should run before this tool)."""
        prerequisites = []
        if not self._graph.has_node(tool_name):
            return prerequisites

        for source, _, data in self._graph.in_edges(tool_name, data=True):
            rel = data.get("relation", "")
            if rel in ("needs_data_from", "often_preceded_by", "should_verify_first"):
                if source.startswith("discord."):
                    prerequisites.append(source)

        return prerequisites

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_feature_requirements(self, tool_name: str, context: Optional[str] = None) -> List[str]:
        """Get guild features required for this tool + context."""
        features = []
        check_node = f"{tool_name}[{context}]" if context else tool_name

        for node in [tool_name, check_node]:
            if not self._graph.has_node(node):
                continue
            for _, target, data in self._graph.out_edges(node, data=True):
                if data.get("relation") == "requires_feature":
                    feat = target.replace("FEATURE:", "")
                    features.append(feat)

        return features

    def get_inverse_tool(self, tool_name: str) -> Optional[str]:
        """Get the inverse/undo tool if one exists."""
        if not self._graph.has_node(tool_name):
            return None

        for _, target, data in self._graph.out_edges(tool_name, data=True):
            if data.get("relation") == "inverse_of" and target.startswith("discord."):
                return target
        return None

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()
