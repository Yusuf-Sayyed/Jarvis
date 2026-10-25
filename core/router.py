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

    # 1. Confirmation Responses (Yes / No)
    if intent == "CONFIRM_ACTION":
        action = params.get("action")
        print(f"[Intent: CONFIRM_ACTION | Action: {action}]")
        if action == "close_tab":
            keyboard.close_browser_tab()
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

    # 4. YouTube Direct Video Playback
    if intent == "YOUTUBE_PLAY_PROMPT":
        print("[Intent: YOUTUBE_PLAY | Awaiting Query]")
        print('\n[JARVIS] "What video or song would you like me to play on YouTube, Sir?"\n')
        return True, "youtube_play"

    if intent == "YOUTUBE_PLAY":
        query = params.get("query", "")
        if not query:
            print("[Intent: YOUTUBE_PLAY | Query Unclear]")
            print('\n[JARVIS] "Please state what video or song you would like to play, Sir."\n')
            return True, "youtube_play"

        print(f"[Intent: YOUTUBE_PLAY | Query: \"{query}\"]")
        browser.play_youtube_video(query)
        return True, None

    if intent == "YOUTUBE_FIRST_RESULT":
        print("[Intent: YOUTUBE_FIRST_RESULT]")
        browser.open_first_youtube_result()
        return True, None

    # 5. Web Search Intent (Search results page)
    if intent == "SEARCH_PROMPT":
        engine = params.get("engine", "google")
        print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Awaiting Query]")
        print(f'\n[JARVIS] "What would you like me to search for on {engine.capitalize()}, Sir?"\n')
        return True, f"search_{engine}"

    if intent == "BROWSER_SEARCH":
        engine = params.get("engine", "google")
        query = params.get("query", "")
        if not query:
            print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Query Unclear]")
            print(f'\n[JARVIS] "I could not identify the search query, Sir. Please say: \'Search {engine.capitalize()} for [your query]\'."\n')
            return True, f"search_{engine}"

        print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Query: \"{query}\"]")
        browser.search_web(query, engine)
        return True, None

    # 6. Typing Intent
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

    # 7. Browser Navigation Actions
    if intent == "BROWSER_ACTION":
        action = params.get("action")
        print(f"[Intent: BROWSER_ACTION | Action: {action}]")
        keyboard.send_browser_shortcut(action)
        return True, None

    # 8. Desktop Core Launch Actions
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

    # 9. Low-confidence / Unclear speech handling
    if intent == "UNCLEAR_SPEECH":
        print("[Intent: UNCLEAR_SPEECH]")
        print('\n[JARVIS] "I beg your pardon, Sir. Could you please repeat that?"\n')
        return True, None

    # 10. Ollama Fallback
    if intent == "OLLAMA_QUERY":
        prompt = params.get("prompt", text)
        ask_ollama(prompt)
        return True, None

    return True, None
