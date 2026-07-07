# categories

## Tools

### create
- description: Create a new channel category in the guild
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - name (str, required): Category name
  - position (int, optional): Category position in the list
  - reason (str, optional): Audit log reason

### delete
- description: Delete an existing category and optionally its channels
- risk: high
- parameters:
  - guild_id (int, required): Target guild ID
  - category_id (int, required): Category ID to delete
  - delete_channels (bool, optional): Whether to delete child channels (default false — orphans them)
  - reason (str, optional): Audit log reason

### rename
- description: Rename an existing category
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - category_id (int, required): Category ID to rename
  - name (str, required): New category name
  - reason (str, optional): Audit log reason

### reorder
- description: Reorder categories by specifying new position mapping
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - positions (dict, required): Mapping of category_id to new position index
  - reason (str, optional): Audit log reason
