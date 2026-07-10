"""DynamoDB Database Layer — Single-Table Design for AuraFactory Phase 2.

Replaces asyncpg/PostgreSQL with DynamoDB while maintaining the same
public interface used by services (context_service, auth_service, etc.)

Single-Table Schema:
─────────────────────────────────────────────────────────────────────
PK (Partition Key)       | SK (Sort Key)              | Entity
─────────────────────────────────────────────────────────────────────
GUILD#{guild_id}         | SNAPSHOT                   | server_snapshots
GUILD#{guild_id}         | SESSION#{session_id}       | sessions
GUILD#{guild_id}         | AUDIT#{timestamp}#{rand}   | audit_log
GUILD#{guild_id}         | BOT_INSTALL                | bot_installs
USER#{user_id}           | PROFILE                    | users (OAuth)
USER#{user_id}           | ADMIN_GUILD#{guild_id}     | guild_admin_cache
SESSION#{session_id}     | META                       | session metadata
─────────────────────────────────────────────────────────────────────

GSI1 (Global Secondary Index):
  PK: GSI1PK = USER#{user_id}
  SK: GSI1SK = SESSION#{guild_id}#{session_id}
  → Lookup sessions by user

TTL:
  - server_snapshots: stale_after (epoch seconds)
  - audit_log: expires_at (90 days retention)

Environment variables:
    DYNAMODB_TABLE_NAME: Table name (default: "aurafactory")
    AWS_REGION: Region (default: us-east-1)

Setup (AWS CLI):
    aws dynamodb create-table \
        --table-name aurafactory \
        --attribute-definitions \
            AttributeName=PK,AttributeType=S \
            AttributeName=SK,AttributeType=S \
            AttributeName=GSI1PK,AttributeType=S \
            AttributeName=GSI1SK,AttributeType=S \
        --key-schema \
            AttributeName=PK,KeyType=HASH \
            AttributeName=SK,KeyType=RANGE \
        --global-secondary-indexes '[{
            "IndexName":"GSI1",
            "KeySchema":[
                {"AttributeName":"GSI1PK","KeyType":"HASH"},
                {"AttributeName":"GSI1SK","KeyType":"RANGE"}
            ],
            "Projection":{"ProjectionType":"ALL"}
        }]' \
        --billing-mode PAY_PER_REQUEST \
        --region us-east-1
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_BOTO_CONFIG = BotoConfig(
    retries={"max_attempts": 3, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=10,
)


class Database:
    """DynamoDB database layer with PostgreSQL-compatible interface.

    Maintains same public methods so services don't need changes:
    - execute(query, *args) → mapped to DynamoDB writes
    - fetch(query, *args) → mapped to DynamoDB queries
    - fetchrow(query, *args) → mapped to DynamoDB get_item
    - fetchval(query, *args) → mapped to DynamoDB scalar

    PLUS new DynamoDB-native methods for direct access.
    """

    def __init__(self, table_name: Optional[str] = None, region: Optional[str] = None) -> None:
        self._table_name = table_name or os.getenv("DYNAMODB_TABLE_NAME", "aurafactory")
        self._region = region or os.getenv("AWS_REGION", "us-east-1")
        self._resource = None
        self._table = None
        self._connected = False

    # ==================================================================
    # Connection lifecycle (compatible with existing main.py)
    # ==================================================================

    async def connect(self) -> None:
        """Initialize DynamoDB resource and verify table exists."""
        self._resource = boto3.resource(
            "dynamodb",
            region_name=self._region,
            config=_BOTO_CONFIG,
        )
        self._table = self._resource.Table(self._table_name)

        # Verify table exists
        try:
            status = await asyncio.to_thread(lambda: self._table.table_status)
            logger.info("DynamoDB table '%s' status: %s", self._table_name, status)
            self._connected = True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.warning(
                    "DynamoDB table '%s' not found — creating it now...",
                    self._table_name,
                )
                await self._create_table()
                self._connected = True
            else:
                raise

    async def disconnect(self) -> None:
        """No-op for DynamoDB (connectionless)."""
        self._connected = False
        logger.info("DynamoDB disconnected (no-op)")

    async def run_migrations(self, migrations_dir: str) -> None:
        """No-op for DynamoDB (schema-less). Kept for main.py compatibility."""
        logger.info("DynamoDB: migrations not needed (schema-less, single-table)")

    @property
    def pool(self):
        """Compatibility property — returns truthy if connected."""
        return self._connected

    # ==================================================================
    # DynamoDB-native methods (preferred for new code)
    # ==================================================================

    async def put_item(self, item: Dict[str, Any]) -> None:
        """Write an item to DynamoDB."""
        clean = self._serialize(item)
        await asyncio.to_thread(self._table.put_item, Item=clean)

    async def get_item(self, pk: str, sk: str) -> Optional[Dict[str, Any]]:
        """Get a single item by primary key."""
        response = await asyncio.to_thread(
            self._table.get_item, Key={"PK": pk, "SK": sk}
        )
        item = response.get("Item")
        return self._deserialize(item) if item else None

    async def query_items(
        self,
        pk: str,
        sk_prefix: Optional[str] = None,
        sk_eq: Optional[str] = None,
        limit: int = 100,
        scan_forward: bool = True,
        index_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query items by partition key with optional sort key filter."""
        kwargs: Dict[str, Any] = {
            "Limit": limit,
            "ScanIndexForward": scan_forward,
        }

        if index_name:
            kwargs["IndexName"] = index_name
            pk_attr = "GSI1PK"
            sk_attr = "GSI1SK"
        else:
            pk_attr = "PK"
            sk_attr = "SK"

        if sk_eq:
            kwargs["KeyConditionExpression"] = (
                Key(pk_attr).eq(pk) & Key(sk_attr).eq(sk_eq)
            )
        elif sk_prefix:
            kwargs["KeyConditionExpression"] = (
                Key(pk_attr).eq(pk) & Key(sk_attr).begins_with(sk_prefix)
            )
        else:
            kwargs["KeyConditionExpression"] = Key(pk_attr).eq(pk)

        response = await asyncio.to_thread(self._table.query, **kwargs)
        return [self._deserialize(item) for item in response.get("Items", [])]

    async def delete_item(self, pk: str, sk: str) -> None:
        """Delete a single item."""
        await asyncio.to_thread(
            self._table.delete_item, Key={"PK": pk, "SK": sk}
        )

    async def update_item(
        self,
        pk: str,
        sk: str,
        updates: Dict[str, Any],
    ) -> None:
        """Update specific attributes of an item."""
        expr_parts = []
        names = {}
        values = {}

        for i, (key, value) in enumerate(updates.items()):
            attr_name = f"#attr{i}"
            attr_val = f":val{i}"
            expr_parts.append(f"{attr_name} = {attr_val}")
            names[attr_name] = key
            values[attr_val] = self._serialize_value(value)

        update_expr = "SET " + ", ".join(expr_parts)

        await asyncio.to_thread(
            self._table.update_item,
            Key={"PK": pk, "SK": sk},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    # ==================================================================
    # PostgreSQL-compatible interface (for existing services)
    # ==================================================================

    async def execute(self, query: str, *args: Any) -> str:
        """Map SQL INSERT/UPDATE/DELETE to DynamoDB operations.

        This is the compatibility layer — it parses the SQL intent and
        routes to the appropriate DynamoDB operation.
        """
        query_lower = query.strip().lower()

        if "server_snapshots" in query_lower:
            return await self._upsert_snapshot(args)
        elif "audit_log" in query_lower:
            return await self._insert_audit(args)
        elif "users" in query_lower and "insert" in query_lower:
            return await self._upsert_user(args)
        elif "guild_admin_cache" in query_lower:
            return await self._upsert_guild_admin(args)
        elif "bot_installs" in query_lower:
            return await self._upsert_bot_install(query_lower, args)
        elif "sessions" in query_lower and "insert" in query_lower:
            return await self._upsert_session(args)
        elif "sessions" in query_lower and "delete" in query_lower:
            return await self._delete_session(args)
        elif "select 1" in query_lower:
            return "SELECT 1"  # Health check
        elif "stale_after" in query_lower and "update" in query_lower:
            return await self._invalidate_snapshot(args)
        else:
            logger.warning("Unmapped SQL execute: %s", query[:80])
            return "OK"

    async def fetch(self, query: str, *args: Any) -> List[Dict[str, Any]]:
        """Map SQL SELECT (multiple rows) to DynamoDB query."""
        query_lower = query.strip().lower()

        if "guild_admin_cache" in query_lower and "bot_installs" in query_lower:
            # JOIN query: get_user_guilds
            user_id = args[0] if args else 0
            return await self._fetch_user_guilds(user_id)
        elif "sessions" in query_lower and "guild_id" in query_lower:
            guild_id = args[0] if args else 0
            return await self._fetch_guild_sessions(guild_id)
        elif "audit_log" in query_lower:
            guild_id = args[0] if args else 0
            return await self._fetch_audit_log(guild_id)
        else:
            logger.warning("Unmapped SQL fetch: %s", query[:80])
            return []

    async def fetchrow(self, query: str, *args: Any) -> Optional[Dict[str, Any]]:
        """Map SQL SELECT (single row) to DynamoDB get_item."""
        query_lower = query.strip().lower()

        if "server_snapshots" in query_lower:
            guild_id = args[0] if args else 0
            return await self._get_snapshot(guild_id)
        elif "sessions" in query_lower:
            session_id = args[0] if args else ""
            return await self._get_session(str(session_id))
        elif "users" in query_lower:
            user_id = args[0] if args else 0
            return await self._get_user(user_id)
        elif "bot_installs" in query_lower:
            guild_id = args[0] if args else 0
            return await self._get_bot_install(guild_id)
        else:
            logger.warning("Unmapped SQL fetchrow: %s", query[:80])
            return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Map SQL SELECT (single value) to DynamoDB."""
        query_lower = query.strip().lower()

        if "select 1" in query_lower:
            return 1  # Health check
        elif "coalesce" in query_lower and "token" in query_lower:
            # Token budget check
            guild_id = args[0] if args else 0
            return await self._get_daily_token_usage(guild_id)
        else:
            row = await self.fetchrow(query, *args)
            if row and isinstance(row, dict):
                # Return first value
                values = list(row.values())
                return values[0] if values else None
            return None

    # ==================================================================
    # Entity-specific operations
    # ==================================================================

    async def _upsert_snapshot(self, args) -> str:
        """Upsert server_snapshots."""
        guild_id = args[0]
        now = datetime.now(timezone.utc)
        item = {
            "PK": f"GUILD#{guild_id}",
            "SK": "SNAPSHOT",
            "entity_type": "server_snapshot",
            "guild_id": guild_id,
            "categories": args[1] if len(args) > 1 else "[]",
            "channels": args[2] if len(args) > 2 else "[]",
            "roles": args[3] if len(args) > 3 else "[]",
            "server_info": args[4] if len(args) > 4 else "{}",
            "snapshot_at": now.isoformat(),
            "stale_after": int((now + timedelta(seconds=60)).timestamp()),  # TTL
            "updated_at": now.isoformat(),
        }
        await self.put_item(item)
        return "UPSERT 1"

    async def _get_snapshot(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get cached snapshot if not stale."""
        item = await self.get_item(f"GUILD#{guild_id}", "SNAPSHOT")
        if not item:
            return None
        # Check if stale
        stale_after = item.get("stale_after", 0)
        if stale_after and time.time() > float(stale_after):
            return None  # Expired
        return item

    async def _invalidate_snapshot(self, args) -> str:
        """Mark snapshot as stale."""
        guild_id = args[0]
        await self.update_item(
            f"GUILD#{guild_id}", "SNAPSHOT",
            {"stale_after": 0}  # Immediately stale
        )
        return "UPDATE 1"

    async def _insert_audit(self, args) -> str:
        """Insert audit log entry."""
        guild_id = args[0]
        now = datetime.now(timezone.utc)
        rand = uuid.uuid4().hex[:8]
        item = {
            "PK": f"GUILD#{guild_id}",
            "SK": f"AUDIT#{now.strftime('%Y%m%d%H%M%S')}#{rand}",
            "entity_type": "audit_log",
            "guild_id": guild_id,
            "user_id": args[1] if len(args) > 1 else 0,
            "tool_name": args[2] if len(args) > 2 else "",
            "tool_params": args[3] if len(args) > 3 else "{}",
            "risk_level": args[4] if len(args) > 4 else "low",
            "success": args[5] if len(args) > 5 else True,
            "duration_ms": args[6] if len(args) > 6 else 0,
            "timestamp": now.isoformat(),
            "expires_at": int((now + timedelta(days=90)).timestamp()),  # TTL: 90 days
        }
        await self.put_item(item)
        return "INSERT 1"

    async def _fetch_audit_log(self, guild_id: int) -> List[Dict[str, Any]]:
        """Fetch recent audit log for a guild."""
        return await self.query_items(
            pk=f"GUILD#{guild_id}",
            sk_prefix="AUDIT#",
            limit=50,
            scan_forward=False,  # Most recent first
        )

    async def _upsert_user(self, args) -> str:
        """Upsert user (OAuth)."""
        user_id = args[0]
        now = datetime.now(timezone.utc)
        item = {
            "PK": f"USER#{user_id}",
            "SK": "PROFILE",
            "entity_type": "user",
            "discord_user_id": user_id,
            "username": args[1] if len(args) > 1 else "",
            "avatar_hash": args[2] if len(args) > 2 else "",
            "access_token_enc": args[3] if len(args) > 3 else "",
            "refresh_token_enc": args[4] if len(args) > 4 else "",
            "token_expires_at": args[5].isoformat() if len(args) > 5 and args[5] else "",
            "last_login_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        await self.put_item(item)
        return "UPSERT 1"

    async def _get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user profile."""
        return await self.get_item(f"USER#{user_id}", "PROFILE")

    async def _upsert_guild_admin(self, args) -> str:
        """Upsert guild_admin_cache entry."""
        user_id = args[0]
        guild_id = args[1]
        now = datetime.now(timezone.utc)
        item = {
            "PK": f"USER#{user_id}",
            "SK": f"ADMIN_GUILD#{guild_id}",
            "entity_type": "guild_admin_cache",
            "user_id": user_id,
            "guild_id": guild_id,
            "guild_name": args[2] if len(args) > 2 else "",
            "is_owner": args[3] if len(args) > 3 else False,
            "permissions_bitfield": args[4] if len(args) > 4 else 0,
            "cached_at": now.isoformat(),
        }
        await self.put_item(item)
        return "UPSERT 1"

    async def _fetch_user_guilds(self, user_id: int) -> List[Dict[str, Any]]:
        """Fetch user's admin guilds with bot install status."""
        guilds = await self.query_items(
            pk=f"USER#{user_id}",
            sk_prefix="ADMIN_GUILD#",
        )

        # Enrich with bot_installed status
        results = []
        for g in guilds:
            guild_id = g.get("guild_id")
            bot_item = await self.get_item(f"GUILD#{guild_id}", "BOT_INSTALL")
            g["bot_installed"] = bool(bot_item and bot_item.get("is_active"))
            results.append(g)
        return results

    async def _upsert_bot_install(self, query_lower: str, args) -> str:
        """Upsert or update bot_installs."""
        guild_id = args[0]

        if "is_active = false" in query_lower or "is_active = FALSE" in query_lower:
            # Unregister
            await self.update_item(
                f"GUILD#{guild_id}", "BOT_INSTALL",
                {"is_active": False}
            )
        else:
            # Register/re-register
            now = datetime.now(timezone.utc)
            item = {
                "PK": f"GUILD#{guild_id}",
                "SK": "BOT_INSTALL",
                "entity_type": "bot_install",
                "guild_id": guild_id,
                "installed_by": args[1] if len(args) > 1 else 0,
                "installed_at": now.isoformat(),
                "is_active": True,
            }
            await self.put_item(item)
        return "UPSERT 1"

    async def _get_bot_install(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get bot install status."""
        return await self.get_item(f"GUILD#{guild_id}", "BOT_INSTALL")

    async def _upsert_session(self, args) -> str:
        """Upsert session."""
        session_id = str(args[0]) if args else str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Determine if args match (id, guild_id, user_id, history) or similar
        item = {
            "PK": f"SESSION#{session_id}",
            "SK": "META",
            "entity_type": "session",
            "id": session_id,
            "guild_id": args[1] if len(args) > 1 else 0,
            "user_id": args[2] if len(args) > 2 else 0,
            "history": args[3] if len(args) > 3 else "[]",
            "updated_at": now.isoformat(),
            "created_at": now.isoformat(),
        }

        # Also add GSI for user lookup
        if len(args) > 2:
            item["GSI1PK"] = f"USER#{args[2]}"
            item["GSI1SK"] = f"SESSION#{args[1] if len(args) > 1 else 0}#{session_id}"

        await self.put_item(item)
        return "UPSERT 1"

    async def _get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID."""
        return await self.get_item(f"SESSION#{session_id}", "META")

    async def _delete_session(self, args) -> str:
        """Delete session."""
        session_id = str(args[0]) if args else ""
        await self.delete_item(f"SESSION#{session_id}", "META")
        return "DELETE 1"

    async def _fetch_guild_sessions(self, guild_id: int) -> List[Dict[str, Any]]:
        """Fetch sessions for a guild — via scan with filter (not ideal but works for hackathon)."""
        # For production: add GSI2 on guild_id
        # For hackathon: this is fine with small dataset
        response = await asyncio.to_thread(
            self._table.scan,
            FilterExpression=Attr("guild_id").eq(guild_id) & Attr("entity_type").eq("session"),
            Limit=50,
        )
        return [self._deserialize(item) for item in response.get("Items", [])]

    async def _get_daily_token_usage(self, guild_id: int) -> int:
        """Get today's total token usage for a guild."""
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        # Query today's audit entries that are LLM calls
        items = await self.query_items(
            pk=f"GUILD#{guild_id}",
            sk_prefix=f"AUDIT#{today}",
        )

        total = 0
        for item in items:
            params = item.get("tool_params", "{}")
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except (json.JSONDecodeError, TypeError):
                    params = {}
            if "tokens_in" in params:
                total += int(params.get("tokens_in", 0)) + int(params.get("tokens_out", 0))
        return total

    # ==================================================================
    # Table creation (auto-create if not exists)
    # ==================================================================

    async def _create_table(self) -> None:
        """Create the DynamoDB table with GSI."""
        client = boto3.client("dynamodb", region_name=self._region, config=_BOTO_CONFIG)

        try:
            await asyncio.to_thread(
                client.create_table,
                TableName=self._table_name,
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                    {"AttributeName": "GSI1PK", "AttributeType": "S"},
                    {"AttributeName": "GSI1SK", "AttributeType": "S"},
                ],
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "GSI1",
                        "KeySchema": [
                            {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                            {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                ],
                BillingMode="PAY_PER_REQUEST",  # On-demand (free tier compatible)
            )
            logger.info("Created DynamoDB table '%s'", self._table_name)

            # Wait for table to be active
            waiter = client.get_waiter("table_exists")
            await asyncio.to_thread(
                waiter.wait, TableName=self._table_name
            )
            logger.info("DynamoDB table '%s' is now ACTIVE", self._table_name)

            # Re-initialize table reference
            self._table = self._resource.Table(self._table_name)

            # Enable TTL
            try:
                await asyncio.to_thread(
                    client.update_time_to_live,
                    TableName=self._table_name,
                    TimeToLiveSpecification={
                        "Enabled": True,
                        "AttributeName": "expires_at",
                    },
                )
                logger.info("TTL enabled on 'expires_at' attribute")
            except ClientError:
                logger.warning("Could not enable TTL (may already be enabled)")

        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceInUseException":
                logger.info("Table already exists (race condition)")
            else:
                raise

    # ==================================================================
    # Serialization helpers
    # ==================================================================

    @classmethod
    def _serialize(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize Python types to DynamoDB-compatible types."""
        clean = {}
        for key, value in item.items():
            clean[key] = cls._serialize_value(value)
        return clean

    @classmethod
    def _serialize_value(cls, value: Any) -> Any:
        """Serialize a single value."""
        if isinstance(value, float):
            return Decimal(str(value))
        elif isinstance(value, dict):
            return {k: cls._serialize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [cls._serialize_value(v) for v in value]
        elif value is None:
            return ""  # DynamoDB doesn't support None in non-null attributes
        return value

    @classmethod
    def _deserialize(cls, item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Deserialize DynamoDB types back to Python types."""
        if not item:
            return None
        clean = {}
        for key, value in item.items():
            if isinstance(value, Decimal):
                # Convert to int if whole number, else float
                clean[key] = int(value) if value == int(value) else float(value)
            else:
                clean[key] = value
        return clean
