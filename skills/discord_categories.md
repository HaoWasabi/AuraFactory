# discord.categories — Knowledge for LLM

## Available Actions
- create, rename, edit, delete, sync, reorder, list

## Key Rules

### Execution Order (CRITICAL)
1. **Always create categories BEFORE channels** that go inside them
2. When deleting a category: channels inside are NOT deleted (they become uncategorized)
3. When syncing: child channels inherit the category's permission overwrites

### Parameters
- `create`: name, position, is_private, allowed_role_ids, allowed_user_ids, advanced_permissions, reason
- `rename`: category_id, name, reason
- `edit`: category_id + any of: name, position, is_private, allowed_role_ids, reason
- `delete`: category_id, reason
- `sync`: category_id (syncs ALL child channels to match category perms)
- `reorder`: positions (list of {id, position} pairs)

### Common Patterns
1. **Setup server from scratch**: Create categories first → then channels inside each
2. **Reorganize**: Move channels between categories (use channels.move with new category_id)
3. **Private section**: Create category with is_private=true → all channels inside inherit privacy

### Limits
- Max 50 categories per guild
- Category name: 1-100 chars
- Position 0 = top of sidebar
