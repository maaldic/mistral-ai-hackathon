TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "answer_to_user",
            "description": "Speak a response to the user. Use this whenever you want to communicate with the user verbally.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to speak to the user. Keep it concise.",
                    }
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_element",
            "description": "Click on an interactive element on the current webpage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_id": {
                        "type": "integer",
                        "description": "The data-agent-id of the element to click.",
                    }
                },
                "required": ["element_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Type text into an input field on the current webpage. Uses instant fill — best for form fields. For search bars or autocomplete inputs, use type_and_submit instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_id": {
                        "type": "integer",
                        "description": "The data-agent-id of the input element.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type into the field.",
                    },
                },
                "required": ["element_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_and_submit",
            "description": "Type text character-by-character into a search bar or autocomplete field, then press Enter to submit. This triggers autocomplete suggestions and debounce timers. Use this for search bars, address fields, and any input that shows suggestions as you type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_id": {
                        "type": "integer",
                        "description": "The data-agent-id of the search/autocomplete input.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type and submit.",
                    },
                },
                "required": ["element_id", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_option",
            "description": "Select an option from a dropdown (native <select> or custom JS dropdown). For native selects, uses the browser API. For custom dropdowns (div-based), clicks to open then finds and clicks the matching option.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_id": {
                        "type": "integer",
                        "description": "The data-agent-id of the dropdown element.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The visible label text of the option to select.",
                    },
                },
                "required": ["element_id", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll_down",
            "description": "Scroll down the current webpage to see more content below.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "Scroll intensity from 1 (small nudge) to 5 (large jump). Default is 3 (one viewport).",
                        "minimum": 1,
                        "maximum": 5,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll_up",
            "description": "Scroll up the current webpage to see previous content above.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "Scroll intensity from 1 (small nudge) to 5 (large jump). Default is 3 (one viewport).",
                        "minimum": 1,
                        "maximum": 5,
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "go_to_url",
            "description": "Navigate the browser to a specific URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to navigate to.",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_iframe_content",
            "description": "Read the interactive elements inside an iframe. Use this when you see an IFRAME listed on the page and need to interact with its contents. Returns the list of clickable/typeable elements inside the iframe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "iframe_id": {
                        "type": "integer",
                        "description": "The iframe ID from the IFRAMES ON PAGE section (e.g. 1 for [iframe-1]).",
                    }
                },
                "required": ["iframe_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_iframe_element",
            "description": "Click an element inside an iframe. You must call get_iframe_content first to discover element IDs inside the iframe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "iframe_id": {
                        "type": "integer",
                        "description": "The iframe ID (e.g. 1 for [iframe-1]).",
                    },
                    "element_id": {
                        "type": "integer",
                        "description": "The data-agent-id of the element inside the iframe.",
                    },
                },
                "required": ["iframe_id", "element_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_iframe_text",
            "description": "Type text into an input field inside an iframe. You must call get_iframe_content first to discover element IDs inside the iframe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "iframe_id": {
                        "type": "integer",
                        "description": "The iframe ID (e.g. 1 for [iframe-1]).",
                    },
                    "element_id": {
                        "type": "integer",
                        "description": "The data-agent-id of the input element inside the iframe.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text to type into the input field.",
                    },
                },
                "required": ["iframe_id", "element_id", "text"],
            },
        },
    },
]
