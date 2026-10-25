"""
Command router: Dispatches detected intents to appropriate action handlers or Ollama.
"""

from actions import browser, desktop, keyboard
from core.intent import detect_intent
from intelligence.ollama_client import ask_ollama


def route_command(text: str, pending_action: str | None = None) -> tuple[bool, str | None]:
    """
    Detects the intent of spoken text and routes it to the proper action.

    Returns:
        (should_continue: bool, new_pending_action: str | None)
    """
    intent, params = detect_intent(text, pending_action)

    # 1. Confirmation Responses
    if intent == "CONFIRM_ACTION":
        action = params.get("action")
        print(f"[Intent: CONFIRM_ACTION | Action: {action}]")
        if action == "close_tab":
            keyboard.send_browser_shortcut("close_tab")
        return True, None

    if intent == "CANCEL_ACTION":
        print("[Intent: CANCEL_ACTION]")
        print("[JARVIS] Action canceled, Sir.")
        return True, None

    # 2. Exit Command
    if intent == "EXIT":
        print("[Intent: EXIT]")
        print("[JARVIS] Goodbye, Sir. Systems powering down.")
        return False, None

    # 3. Actions Requiring Confirmation (e.g. Close Tab)
    if intent == "REQUEST_CONFIRMATION":
        action = params.get("action")
        print(f"[Intent: BROWSER_ACTION | Action: Close Current Tab (Confirmation Required)]")
        print("\n[JARVIS] \"Are you sure you want to close the current tab, Sir?\"")
        print("         Say 'yes' to confirm or 'no' to cancel.\n")
        return True, action

    # 4. Web Search Intent
    if intent == "BROWSER_SEARCH":
        engine = params.get("engine", "google")
        query = params.get("query", "")
        if not query:
            print("[Intent: BROWSER_SEARCH | Query Unclear]")
            print("[JARVIS] \"I could not identify the search query, Sir. Please say: 'Search Google for [your query]'.\"")
            return True, None

        print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Query: \"{query}\"]")
        browser.search_web(query, engine)
        return True, None

    # 5. Typing Intent
    if intent == "TYPE_TEXT":
        content = params.get("content", "")
        press_enter = params.get("press_enter", False)
        if not content:
            print("[Intent: TYPE_TEXT | Content Unclear]")
            print("[JARVIS] \"Please state what text you would like me to type, Sir.\"")
            return True, None

        print(f"[Intent: TYPE_TEXT | Text: \"{content}\" | Press Enter: {press_enter}]")
        keyboard.type_text(content, press_enter)
        return True, None

    # 6. Browser Navigation Actions
    if intent == "BROWSER_ACTION":
        action = params.get("action")
        print(f"[Intent: BROWSER_ACTION | Action: {action}]")
        keyboard.send_browser_shortcut(action)
        return True, None

    # 7. Desktop Core Launch Actions
    if intent == "DESKTOP_ACTION":
        action = params.get("action")
        print(f"[Intent: DESKTOP_ACTION | Action: {action}]")
        action_map = {
            "open_firefox": desktop.open_firefox,
            "open_firefox_tab": browser.open_firefox_tab,
            "open_firefox_window": browser.open_firefox_window,
            "open_terminal": desktop.open_terminal,
            "open_downloads": desktop.open_downloads,
            "open_youtube": desktop.open_youtube,
        }
        fn = action_map.get(action)
        if fn:
            try:
                fn()
            except Exception as e:
                print(f"[JARVIS Error] Failed to execute action '{action}': {e}")
        return True, None

    # 8. Ollama Fallback
    if intent == "OLLAMA_QUERY":
        prompt = params.get("prompt", text)
        ask_ollama(prompt)
        return True, None

    return True, None
