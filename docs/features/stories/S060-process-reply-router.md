# S060: Process Reply Router

## User Story

As a system operator, I want replies automatically routed to process managers so that processes advance without manual intervention.

## Acceptance Criteria

### AC1: ProcessReplyRouter Class
- Given reply routing is needed
- When I create ProcessReplyRouter(pool, process_repo, managers, reply_queue)
- Then it's configured to route replies to the appropriate managers

### AC2: run() Method
- Given router should run continuously
- When I call run(poll_interval)
- Then it polls reply queue and processes messages in a loop

### AC3: Reply to Process Lookup
- Given a reply has correlation_id
- When router processes the reply
- Then it looks up process by correlation_id (which IS the process_id)

### AC4: Manager Dispatch
- Given process is found and manager exists
- When router dispatches to manager
- Then it calls manager.handle_reply(reply, process)

### AC5: Unknown Process Handling
- Given correlation_id doesn't match any process
- When router processes the reply
- Then it logs warning and deletes message from queue

### AC6: No Manager Handling
- Given process exists but no manager for process_type
- When router processes the reply
- Then it logs error and deletes message from queue

### AC7: Reply Without Correlation
- Given a reply has no correlation_id
- When router processes the reply
- Then it logs warning and deletes message (not a process reply)

### AC8: Error Handling
- Given handle_reply throws exception
- When router catches error
- Then message is left for retry (visibility timeout will resurface it)

### AC9: Stop Method
- Given router is running
- When stop() is called
- Then the run loop exits gracefully

## Implementation Notes

- Location: `src/commandbus/process/router.py`
- managers dict is keyed by process_type string
- Uses PgmqClient for queue operations
- Reply's correlation_id IS the process_id by convention

## Message Flow

```
1. PGMQ message arrives on reply_queue
2. Router reads message with visibility_timeout=30
3. Extract Reply from message payload
4. Check correlation_id exists
5. Look up process by correlation_id
6. Find manager by process.process_type
7. Call manager.handle_reply(reply, process)
8. Delete message from queue
9. Repeat
```

## Error Recovery

```python
try:
    await manager.handle_reply(reply, process)
    await self.pgmq.delete(reply_queue, msg.msg_id, conn=conn)
except Exception:
    logger.exception(f"Error handling reply for {process.process_id}")
    # Message NOT deleted - will reappear after visibility_timeout
```

## Verification

- [ ] Router consumes from correct queue
- [ ] Replies dispatched to correct manager
- [ ] Unknown processes logged and messages deleted
- [ ] Errors leave messages for retry
- [ ] stop() cleanly exits loop
