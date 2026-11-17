"""The macro catalog's examples for steward's own macros, merged into
``macro_catalog.EXAMPLES`` there; the framework's stay in that file."""

# Steward's macros that act on the whole page, shown as code only.
APP_CODE_ONLY = frozenset({"confirm_permanent", "sse_job"})

APP_EXAMPLES: dict[str, dict[str, str]] = {
    "layout": {
        "brand": """{{ brand("Steward") }}""",
        "nav_item": """
            {% set section = {"key": "overview", "label": "Overview", "path": "/overview",
                              "icon": "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-9.5Z"} %}
            <nav class="w-56">{{ nav_item(section, "/overview") }}</nav>""",
        "appearance_fields": """
            <div x-data="{ ...appearance() }" class="w-64 space-y-2">{{ appearance_fields() }}</div>""",
        "chip_nav": """
            {{ chip_nav("catalog-window", "Window", [("30d", True, "#macro-chip_nav"), ("90d", False, "#macro-chip_nav")], "#catalog-window") }}""",
        "mark": """
            <span class="inline-flex items-center gap-3">
              {{ mark({"icon_url": None, "category": "Groceries"}, "Market") }}
              {{ mark({"icon_url": None, "category": None}, "Rent") }}
            </span>""",
        "file_mark": """{{ file_mark(file_badge("application/pdf", "statement.pdf")) }}""",
        "contact_link": """{{ contact_link(7, "County Clerk") }}""",
        "page_link": """{{ page_link("/settings/activity", "Activity") }}""",
        "local_time": """{{ local_time("2026-10-19T02:19:05") }}""",
        "doors": """
            {{ doors([{"label": "Checking", "url": "/accounts/1"}, {"label": "Taxes", "url": "/matters/2"},
                      {"label": "Renewal", "url": "/matters/3"}], show=2) }}""",
        "dot": """
            <span class="flex items-center gap-3">
              {{ dot("ok", "Synced today") }} {{ dot("warn", "A week old") }} {{ dot("error", "A month old") }}
            </span>""",
        "remove_button": """
            <div class="flex w-48 items-center">Groceries{{ remove_button("/budget/envelopes/1/remove", "Remove Groceries") }}</div>""",
        "item_grid": """
            {% call item_grid("catalog-goals") %}
              {% call item_card("catalog-goal-1") %}<p class="text-sm">Emergency fund</p>{% endcall %}
              {% call item_card("catalog-goal-2") %}<p class="text-sm">New roof</p>{% endcall %}
            {% endcall %}""",
        "item_card": """
            <ul class="grid gap-4 sm:grid-cols-2">
              {% call item_card("catalog-card") %}<p class="text-sm">One card of a grid</p>{% endcall %}
            </ul>""",
    },
    "feedback": {
        "sse_job": """
            {# Follows /jobs/<id>/events until the job's terminal frame. #}
            {{ sse_job("import-42", "Importing") }}""",
        "unfiled_notice": """
            {{ unfiled_notice(5000) }}""",
        "notice": """
            {{ notice("catalog-waiting", 3, "/review", "3 transactions are waiting for review") }}""",
    },
    "form": {
        "account_filter": """
            {# The accounts' dropdown needs account rows (account_sections); without
               any the filter is its window chips. #}
            {{ account_filter("/overview", [], [], 30, [(30, "30d"), (90, "90d")]) }}""",
        "control": """<input type="text" placeholder="A bare control" class="{{ control('input') }}">""",
        "button_classes": """
            <span class="flex gap-2">
              <button type="button" class="{{ button_classes() }}">Save</button>
              <button type="button" class="{{ button_classes('default') }}">Cancel</button>
            </span>""",
        "check_apply": """<form>{{ check_apply("Merge", True) }}</form>""",
        "summary_panel": """
            {% call summary_panel('data-summary') %}<dt>Rows</dt><dd class="text-right">12</dd>{% endcall %}""",
        "pick_or_add": """
            {{ pick_or_add("payee_id", [{"id": 1, "name": "Market"}, {"id": 2, "name": "Landlord"}], new_field="payee_name") }}""",
        "file_input": """{{ file_input("document", accept=".pdf") }}""",
        "picker": """
            {{ picker("catalog-picker", "/register/1/payee", "payee_id",
                      [{"id": 1, "name": "Market", "fact": "12x"}, {"id": 2, "name": "Landlord"}],
                      hint="Search payees", create="payee_name") }}""",
        "target_inputs": """<form>{{ target_inputs(4, None, None) }}</form>""",
        "money_edit": """<form>{{ money_edit("limit", "400.00", "$400.00", "Edit the limit") }}</form>""",
        "term_fields": """
            {% set terms = [{"name": "rate", "label": "Rate", "kind": "text", "choices": ()},
                            {"name": "opened", "label": "Opened", "kind": "date", "choices": ()}] %}
            {{ term_fields(terms, {"rate": "6.25%"}) }}""",
        "chip_select": """
            {{ chip_select("places", [{"id": 1, "name": "Checking"}, {"id": 2, "name": "Taxes"}], [{"id": 1, "name": "Checking"}]) }}""",
        "line_row": """{{ line_row("label", "value", "Policy", "H-123") }}""",
        "line_rows": """{{ line_rows("label", "value", [("Policy", "H-123")]) }}""",
        "confirm_permanent": """
            {# Below a dialog's archive action; the route checks the typed name. #}
            {{ confirm_permanent("this account", "Checking", "/accounts/1/purge") }}""",
    },
    "table": {
        "new_dot": """<span class="inline-flex items-center gap-2 text-sm">{{ new_dot() }} New</span>""",
        "new_mark": """
            <table class="w-full text-sm"><tbody><tr><td class="relative pl-5">{{ new_mark({"is_new": True, "import_batch_id": None}) }}Coffee</td></tr></tbody></table>""",
    },
}
