# Privacy Policy — AuraFactory

**Last Updated**: 2024-07-04

## 1. Data Collection
AuraFactory processes Discord messages ONLY when:
- Bot is explicitly mentioned (@AuraFactory)
- A slash command is invoked
- A request is sent through the web interface (AFfrontend)

We do NOT store message content after processing. Only metadata (trace logs) are retained for debugging.

## 2. Data Processed
- Discord user ID and username (for context)
- Guild/Channel IDs (for executing actions)
- Message content (for AI interpretation — not stored permanently)

## 3. AI Processing  
- User messages are sent to LLM providers (Google Gemini / AWS Bedrock) for interpretation
- No message content is used for model training
- Responses are ephemeral and not logged beyond trace data

## 4. Trace Logs
- Stored locally in `logs/` folder
- Contain: trace_id, timestamp, agent actions, tool calls
- Do NOT contain: message content, user data
- Auto-purged after 30 days

## 5. Third-party Services
| Service | Purpose | Data Sent |
|---------|---------|-----------|
| Google Gemini | LLM inference | Sanitized prompts |
| Discord API | Bot actions | Commands only |

## 6. User Rights
- You may request deletion of trace logs at any time
- Bot admin can purge all data via `/admin purge-logs`
- No data is sold or shared with third parties

## 7. Contact
For privacy concerns: [Your contact email]
