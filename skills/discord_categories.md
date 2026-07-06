# Skill: Discord Category Management

## Agent: architect
## Risk: medium
## Category: categories

### Tools

#### create_category
- Description: Create a new channel category to organize channels.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - name (string, required): Category name (displayed in UPPERCASE)
  - position (integer): Position in server channel list
- Risk: medium
- Requires Approval: no
- Examples:
  - Input: {"guild_id": 123456, "name": "THÔNG TIN CHUNG"}
  - Output: {"category_id": 789, "name": "THÔNG TIN CHUNG"}

#### delete_category
- Description: Delete a category. Channels inside will become uncategorized (not deleted).
- Parameters:
  - guild_id (integer, required): Target guild ID
  - category_name (string, required): Category name to delete
  - reason (string): Audit log reason
- Risk: high
- Requires Approval: yes

#### rename_category
- Description: Rename an existing category.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - category_name (string, required): Current category name
  - new_name (string, required): New name
- Risk: medium
- Requires Approval: no

#### list_categories
- Description: List all categories with their channels.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - include_channels (boolean, default: true): Include channels under each category
- Risk: low
- Requires Approval: no
