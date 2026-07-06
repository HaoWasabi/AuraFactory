-- ============================================================
-- AuraFactory — Seed Data
-- Default agents + capabilities
-- ============================================================

-- Default Agents
INSERT INTO agents (agent_id, display_name, description, model_preference) VALUES
('orchestrator', 'Orchestrator', 'Routes requests, plans multi-step tasks, delegates to specialists', 'gemini-2.5-flash'),
('architect', 'Architect', 'Handles workspace structure: channels, categories, roles, permissions', 'gemini-2.5-flash'),
('copilot', 'Copilot', 'Answers questions, gives suggestions, handles simple queries', 'gemini-2.5-flash')
ON CONFLICT (agent_id) DO NOTHING;

-- Agent Capabilities
INSERT INTO agent_capabilities (agent_id, capability) VALUES
-- Orchestrator: routing only, no direct Discord actions
('orchestrator', 'route_request'),
('orchestrator', 'plan_tasks'),
('orchestrator', 'delegate_agent'),
-- Architect: full workspace management
('architect', 'create_channel'),
('architect', 'delete_channel'),
('architect', 'edit_channel'),
('architect', 'create_category'),
('architect', 'delete_category'),
('architect', 'create_role'),
('architect', 'delete_role'),
('architect', 'edit_role'),
('architect', 'assign_role'),
('architect', 'manage_permissions'),
('architect', 'manage_webhooks'),
('architect', 'backup_guild'),
-- Copilot: read-only + messaging
('copilot', 'read_guild_info'),
('copilot', 'read_channels'),
('copilot', 'read_members'),
('copilot', 'read_roles'),
('copilot', 'send_message')
ON CONFLICT (agent_id, capability) DO NOTHING;
