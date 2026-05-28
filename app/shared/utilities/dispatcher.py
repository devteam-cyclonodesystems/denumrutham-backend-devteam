"""
Asynchronous Event Dispatcher for Temple Management System.
"""
from typing import Any, Dict
from fastapi import BackgroundTasks
import logging

logger = logging.getLogger(__name__)

class EventDispatcher:
    _handlers = {}

    @classmethod
    def register(cls, event_name: str, handler: callable):
        if event_name not in cls._handlers:
            cls._handlers[event_name] = []
        cls._handlers[event_name].append(handler)
        logger.info(f"Registered handler for event: {event_name}")

    @classmethod
    def dispatch(cls, event_name: str, payload: Dict[str, Any], background_tasks: BackgroundTasks):
        """Dispatch an event asynchronously using FastAPI BackgroundTasks."""
        handlers = cls._handlers.get(event_name, [])
        if not handlers:
            logger.debug(f"No handlers registered for event: {event_name}")
            return
            
        for handler in handlers:
            logger.info(f"Dispatching event '{event_name}' to handler '{handler.__name__}'")
            background_tasks.add_task(handler, payload)
