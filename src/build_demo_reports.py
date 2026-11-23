"""Build connected PBIR and paginated RDL reports for Client Analytics."""

import argparse
import base64
import copy
import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from organize_model_layout import organize

ROOT = Path(__file__).parent
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/"
REPORT_NAME = "Client Analytics - Interactive"
RDL_NAME = "Client Analytics - Advisor Pack"
NAVY, TEAL, INK, MUTED, PAPER = "#12304A", "#007F82", "#203548", "#546779", "#F2F5F8"
PAGES = {
    "executive": "01 Executive Overview",
    "advisors": "02 Advisor Performance",
    "pipeline": "03 Pipeline and Campaigns",
    "guide": "04 Solution Guide",
    "client": "Client Detail",
}
RDL_NS = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"
RD_NS = "http://schemas.microsoft.com/SQLServer/reporting/reportdesigner"
ET.register_namespace("", RDL_NS)
ET.register_namespace("rd", RD_NS)


def literal(value):
    if isinstance(value, bool):
        value = str(value).lower()
    elif isinstance(value, str):
        value = "'" + value.replace("'", "''") + "'"
    else:
        value = str(value) + "D"
    return {"expr": {"Literal": {"Value": value}}}


def color(value):
    return {"solid": {"color": literal(value)}}


def field(table, prop, measure=False):
    return {("Measure" if measure else "Column"): {
        "Expression": {"SourceRef": {"Entity": table}}, "Property": prop,
    }}


def projection(table, prop, measure=False, **extra):
    return {"field": field(table, prop, measure), "queryRef": f"{table}.{prop}", **extra}


def categorical(table, prop, values):
    return {
        "Version": 2, "From": [{"Name": "s", "Entity": table, "Type": 0}],
        "Where": [{"Condition": {"In": {
            "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": prop}}],
            "Values": [[{"Literal": literal(v)["expr"]["Literal"]}] for v in values],
        }}}],
    }


def filter_card(name, table, prop, values=None, origin="User"):
    result = {"name": name, "field": field(table, prop), "type": "Categorical", "howCreated": origin}
    if values is not None:
        result["filter"] = categorical(table, prop, values)
    return result


class Report:
    def __init__(self, model):
        self.parts = {}
        self.model = model
        self.measures = {m["name"]: t["name"] for t in model["tables"] for m in t.get("measures", [])}
        self.pages = {}
        self.visuals = {}

    def put(self, path, value):
        self.parts[path] = value
        return value

    def page(self, name):
        page = {
            "$schema": SCHEMA + "definition/page/2.0.0/schema.json",
            "name": name, "displayName": PAGES[name], "displayOption": "FitToPage",
            "height": 900, "width": 1440,
            "objects": {"background": [{"properties": {"color": color(PAPER), "transparency": literal(0)}}]},
        }
        self.pages[name] = self.put(f"definition/pages/{name}/page.json", page)
        self.visuals[name] = []
        return page

    def visual(self, page, name, kind, box, title="", roles=None):
        x, y, width, height = box
        visual = {
            "$schema": SCHEMA + "definition/visualContainer/2.0.0/schema.json",
            "name": name,
            "position": {"x": x, "y": y, "width": width, "height": height,
                         "z": len(self.visuals[page]), "tabOrder": len(self.visuals[page])},
            "visual": {
                "visualType": kind,
                "visualContainerObjects": {
                    "background": [{"properties": {"show": literal(True), "color": color("#FFFFFF"),
                                                  "transparency": literal(0)}}],
                    "title": [{"properties": {"show": literal(bool(title)), "text": literal(title),
                                             "fontColor": color(INK), "fontSize": literal(12)}}],
                    "border": [{"properties": {"show": literal(False)}}],
                },
                "drillFilterOtherVisuals": True,
            },
        }
        if roles:
            visual["visual"]["query"] = {"queryState": {
                role: {"projections": columns} for role, columns in roles.items()
            }}
        self.visuals[page].append(visual)
        return self.put(f"definition/pages/{page}/visuals/{name}/visual.json", visual)

    def text(self, page, name, box, text, size=12, heading=False):
        v = self.visual(page, name, "textbox", box)
        v["visual"]["objects"] = {"general": [{"properties": {"paragraphs": [
            {"textRuns": [{"value": line, "textStyle": {
                "fontFamily": "Segoe UI", "fontSize": f"{size}pt",
                "color": NAVY if heading else INK, "fontWeight": "bold" if heading else "normal",
            }}]} for line in text.split("\n")
        ]}}]}
        return v

    def button(self, page, name, box, text, action, target=None):
        v = self.visual(page, name, "actionButton", box)
        v["visual"]["objects"] = {
            "text": [
                {"properties": {"show": literal(True)}},
                {"selector": {"id": "default"}, "properties": {
                    "text": literal(text), "fontSize": literal(11), "fontColor": color("#FFFFFF"),
                    "horizontalAlignment": literal("center")}},
            ],
            "fill": [
                {"properties": {"show": literal(True)}},
                {"selector": {"id": "default"}, "properties": {"fillColor": color(NAVY)}},
                {"selector": {"id": "hover"}, "properties": {"fillColor": color(TEAL)}},
            ],
            "outline": [{"properties": {"show": literal(False)}}],
            "icon": [{"properties": {"show": literal(False)}}],
        }
        link = {"show": literal(True), "type": literal(action)}
        if target is not None:
            key = {"PageNavigation": "navigationSection", "Bookmark": "bookmark",
                   "WebUrl": "webUrl", "Drillthrough": "drillthroughSection"}[action]
            link[key] = literal(target)
        v["visual"]["visualContainerObjects"]["visualLink"] = [{"properties": link}]
        return v

    def header(self, page, subtitle):
        self.text(page, f"{page}_title", (32, 18, 1376, 48), PAGES[page], 24, True)
        for i, (name, label) in enumerate(list(PAGES.items())[:4]):
            self.button(page, f"{page}_nav_{name}", (32 + i * 224, 78, 212, 38),
                        label[3:], "PageNavigation", name)
        self.button(page, f"{page}_learn", (928, 78, 224, 38), "Power BI documentation",
                    "WebUrl", "https://learn.microsoft.com/power-bi/")
        self.text(page, f"{page}_footer", (32, 854, 1376, 30),
                  "SYNTHETIC DATA | CAD | " + subtitle, 10)

    def slicer(self, page, name, box, table, prop, title, values=None):
        v = self.visual(page, name, "slicer", box, title, {"Values": [projection(table, prop)]})
        v["visual"]["objects"] = {
            "data": [{"properties": {"mode": literal("Dropdown")}}],
            "selection": [{"properties": {"singleSelect": literal(values is not None)}}],
        }
        if values is not None:
            v["visual"]["objects"]["general"] = [
                {"properties": {"filter": {"filter": categorical(table, prop, values)}}}
            ]
        return v

    def card(self, page, name, box, measure):
        return self.visual(page, name, "card", box, measure, {
            "Values": [projection(self.measures[measure], measure, True)]})

    def chart(self, page, name, box, kind, title, dimensions, measures):
        return self.visual(page, name, kind, box, title, {
            "Category": [projection(t, c, active=i == 0) for i, (t, c) in enumerate(dimensions)],
            "Y": [projection(self.measures[m], m, True) for m in measures],
        })

    def table(self, page, name, box, title, columns, measures):
        return self.visual(page, name, "tableEx", box, title, {
            "Values": [projection(t, c) for t, c in columns]
            + [projection(self.measures[m], m, True) for m in measures],
        })


def build_interactive(database, model_id, paginated_url, layout):
    report = Report(database["model"])
    report.put("definition.pbir", {
        "$schema": SCHEMA + "definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={model_id}"}},
    })
    report.put("definition/version.json", {
        "$schema": SCHEMA + "definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0",
    })
    report.put("definition/report.json", {
        "$schema": SCHEMA + "definition/report/3.1.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY25SU12", "type": "SharedResources",
                          "reportVersionAtImport": {"visual": "2.0.0", "report": "3.1.0", "page": "2.0.0"}},
            "customTheme": {"name": "ClientAnalytics", "type": "RegisteredResources",
                            "reportVersionAtImport": {"visual": "2.0.0", "report": "3.1.0", "page": "2.0.0"}},
        },
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": "CY25SU12", "path": "BaseThemes/CY25SU12.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "ClientAnalytics", "path": "ClientAnalytics.json", "type": "CustomTheme"}]},
        ],
        "settings": {
            "isPersistentUserStateDisabled": False, "hideVisualContainerHeader": False,
            "useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarizedAndUnderlying",
            "defaultFilterActionIsDataFilter": False, "defaultDrillFilterOtherVisuals": True,
            "allowChangeFilterTypes": True, "allowInlineExploration": True, "useEnhancedTooltips": True,
        },
        "slowDataSourceSettings": {"isCrossHighlightingDisabled": False},
    })
    report.put("StaticResources/RegisteredResources/ClientAnalytics.json", {
        "name": "ClientAnalytics", "dataColors": [TEAL, NAVY, "#D69A30", "#7198BD", "#8963A6", "#D05A50"],
        "background": "#FFFFFF", "foreground": INK, "tableAccent": TEAL,
        "textClasses": {"title": {"fontFace": "Segoe UI", "color": INK},
                        "label": {"fontFace": "Segoe UI", "color": MUTED}},
    })
    report.put("semanticModelDiagramLayout.json", layout)
    report.put("definition/pages/pages.json", {
        "$schema": SCHEMA + "definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": list(PAGES), "activePageName": "executive",
    })
    for name in PAGES:
        report.page(name)

    report.header("executive", "Select a region to highlight products and filter the trend and client list.")
    report.slicer("executive", "ex_month", (32, 132, 440, 72), "Calendar", "Year Month", "Month")
    report.slicer("executive", "ex_region", (488, 132, 440, 72), "Clients", "Region", "Client region")
    report.slicer("executive", "ex_segment", (944, 132, 464, 72), "Clients", "Segment", "Client segment")
    for i, measure in enumerate(["Assets Under Management", "Revenue", "Profit Margin", "Transaction Count"]):
        report.card("executive", f"ex_kpi_{i}", (32 + i * 348, 220, 332, 96), measure)
    report.chart("executive", "ex_regions", (32, 332, 672, 230), "barChart",
                 "Revenue by client region - click to select", [("Clients", "Region")], ["Revenue"])
    report.chart("executive", "ex_products", (720, 332, 688, 230), "columnChart",
                 "Revenue by product - receives cross-highlighting",
                 [("Products", "Product Family"), ("Products", "Product Name")], ["Revenue"])
    report.chart("executive", "ex_trend", (32, 578, 672, 250), "lineChart",
                 "Revenue - drill Year > Quarter > Month",
                 [("Calendar", "Calendar Year"), ("Calendar", "Calendar Quarter"), ("Calendar", "Year Month")],
                 ["Revenue"])
    report.table("executive", "ex_clients", (720, 578, 688, 250),
                 "Clients - right-click a name > Drill through > Client Detail",
                 [("Clients", "Client Name")], ["Assets Under Management", "Revenue"])
    report.pages["executive"]["visualInteractions"] = [
        {"source": "ex_regions", "target": "ex_products", "type": "HighlightFilter"},
        {"source": "ex_regions", "target": "ex_trend", "type": "DataFilter"},
        {"source": "ex_regions", "target": "ex_clients", "type": "DataFilter"},
    ]
    report.pages["executive"]["filterConfig"] = {
        "filters": [filter_card("regionPreset", "Clients", "Region")]}

    report.header("advisors", "Targets come from Excel. Choose ONE Plan/Stretch scenario; targets are not client-level.")
    report.slicer("advisors", "ad_month", (32, 132, 440, 72), "Calendar", "Year Month", "Month", ["2026-10"])
    report.slicer("advisors", "ad_region", (488, 132, 440, 72), "Advisors", "Advisor Region", "Advisor region")
    report.slicer("advisors", "ad_scenario", (944, 132, 464, 72), "Targets", "Scenario", "Excel planning scenario", ["Plan"])
    for i, measure in enumerate(["Revenue", "Revenue Target", "Revenue Variance", "Revenue Attainment"]):
        report.card("advisors", f"ad_kpi_{i}", (32 + i * 348, 220, 332, 96), measure)
    report.chart("advisors", "ad_org", (32, 332, 672, 230), "columnChart",
                 "Revenue versus Excel plan - drill Region > Branch > Advisor",
                 [("Advisors", "Advisor Region"), ("Advisors", "Branch Name"), ("Advisors", "Advisor Name")],
                 ["Revenue", "Revenue Target"])
    report.chart("advisors", "ad_product", (720, 332, 688, 230), "barChart",
                 "Product performance", [("Products", "Product Family"), ("Products", "Product Name")],
                 ["Revenue", "Revenue Target"])
    report.table("advisors", "ad_detail", (32, 578, 1112, 250),
                 "Advisor / product detail - scrolling table; use the pack to print every row",
                 [("Advisors", "Advisor Name"), ("Products", "Product Name")],
                 ["Assets Under Management", "Revenue", "Revenue Target", "Revenue Attainment"])
    report.button("advisors", "ad_pack", (1160, 578, 248, 54), "Open paginated pack", "WebUrl", paginated_url)
    report.text("advisors", "ad_export_note", (1160, 648, 248, 180),
                "PDF: fixed pages, full detail.\nExcel: formatted table.\nCSV: flat, unformatted data.\nChoose matching parameters in the pack.", 11)

    report.header("pipeline", "Excel Campaigns filter PostgreSQL opportunities and Direct Lake interactions.")
    report.slicer("pipeline", "pi_month", (32, 132, 440, 72), "Calendar", "Year Month", "Date role depends on measure")
    report.slicer("pipeline", "pi_campaign", (488, 132, 440, 72), "Campaigns", "Campaign Name", "Excel campaign")
    report.slicer("pipeline", "pi_stage", (944, 132, 464, 72), "Opportunities", "Stage", "Opportunity stage")
    for i, measure in enumerate(["Opportunity Count", "Open Weighted Pipeline", "Expected Close Pipeline", "Won Value"]):
        report.card("pipeline", f"pi_kpi_{i}", (32 + i * 348, 220, 332, 96), measure)
    report.chart("pipeline", "pi_campaigns", (32, 332, 672, 230), "barChart",
                 "Opportunities by Excel campaign", [("Campaigns", "Campaign Name")], ["Opportunity Count"])
    report.chart("pipeline", "pi_channels", (720, 332, 688, 230), "columnChart",
                 "Campaign interactions by channel", [("Channels", "Channel Name")], ["Interaction Count"])
    report.table("pipeline", "pi_clients", (32, 578, 1376, 250),
                 "Opportunity clients - right-click a client to drill through",
                 [("Clients", "Client Name"), ("Opportunities", "Stage")],
                 ["Opportunity Count", "Estimated Opportunity Value"])
    report.pages["pipeline"]["visualInteractions"] = [
        {"source": "pi_campaigns", "target": "pi_channels", "type": "DataFilter"},
        {"source": "pi_campaigns", "target": "pi_clients", "type": "DataFilter"},
    ]

    report.header("client", "Client drill-through retains historical client versions; booking and settlement dates stay separate.")
    report.pages["client"].update({
        "type": "Drillthrough", "visibility": "HiddenInViewMode",
        "filterConfig": {"filters": [filter_card("clientDrill", "Clients", "Client Name", origin="Drillthrough")]},
        "pageBinding": {"name": "clientBinding", "type": "Drillthrough", "acceptsFilterContext": "Default",
                        "parameters": [{"name": "clientName", "boundFilter": "clientDrill",
                                        "fieldExpr": field("Clients", "Client Name")}]},
    })
    report.button("client", "cl_back", (32, 132, 200, 52), "Back", "Back")
    report.table("client", "cl_identity", (248, 132, 1160, 72), "Selected client", [("Clients", "Client Name")], [])
    for i, measure in enumerate(["Assets Under Management", "Transaction Count", "Interaction Count", "Opportunity Count"]):
        report.card("client", f"cl_kpi_{i}", (32 + i * 348, 220, 332, 96), measure)
    report.chart("client", "cl_dates", (32, 332, 672, 230), "columnChart",
                 "Booking versus settlement - inactive date relationship",
                 [("Calendar", "Year Month")], ["Net Contributions", "Settled Net Contributions"])
    report.chart("client", "cl_aum", (720, 332, 688, 230), "lineChart",
                 "Month-end AUM - never sum balances across months",
                 [("Calendar", "Year Month")], ["Assets Under Management"])
    report.table("client", "cl_accounts", (32, 578, 1376, 250), "Account balances and performance",
                 [("Accounts", "Account Number"), ("Accounts", "Account Type")],
                 ["Assets Under Management", "Revenue", "Transaction Count"])

    report.header("guide", "Tenant permissions, licensing and authenticated connections still apply to every feature.")
    report.text("guide", "gu_interact", (32, 132, 672, 270),
                "INTERACTION WALKTHROUGH\n"
                "1. Overview: select a region; products highlight while the trend filters.\n"
                "2. Use chart drill controls for year/quarter/month or product levels.\n"
                "3. Right-click a client name and drill through to Client Detail.\n"
                "4. Advisor Performance: select a month and ONE planning scenario.\n"
                "5. Use the buttons below to apply authored bookmark presets.\n"
                "6. Bookmarks pane > Add a personal bookmark saves your own filters.\n"
                "Buttons use normal clicks in reading mode; Ctrl+click in edit mode.", 12)
    report.text("guide", "gu_data", (720, 132, 688, 270),
                "SOURCE AND MODEL GUIDE\n"
                "Excel / CA Planning: Campaigns and Targets (Import).\n"
                "PostgreSQL: Opportunities (Import).\n"
                "SQL Server: Clients and Advisors (DirectQuery).\n"
                "Databricks: Transactions (DirectQuery).\n"
                "Gold lakehouse: eight tables (Direct Lake).\n"
                "Five facts share dimensions; Account Ownership is a bridge.\n"
                "Source workbook: 13 campaigns and 54,400 targets; live counts require refresh.", 12)
    report.text("guide", "gu_delivery", (32, 418, 672, 290),
                "DELIVERY AND PRINTING\n"
                "Interactive PDF captures page layouts, not all hidden scroll rows.\n"
                "Use the Advisor Pack for automatically paginated full detail.\n"
                "PDF is print-oriented; Excel adapts layout; CSV has no formatting.\n"
                "Subscribe in the service for scheduled email delivery.\n"
                "Report snapshots and PDF attachments depend on capacity/settings.\n"
                "Power BI dashboard alerts require supported pinned KPI/card tiles.\n"
                "Activator alerts are separate from PDF/image subscriptions.\n"
                "No email recipient or active alert was configured by this report.", 12)
    report.text("guide", "gu_embed", (720, 418, 688, 290),
                "SECURE EMBEDDING\n"
                "Secure iframe embedding retains permissions and RLS.\n"
                "An iframe may prompt for sign-in; autoAuth is not guaranteed SSO.\n"
                "ClientFirst seamless SSO needs Entra app integration and the SDK.\n"
                "Use a signed-in user's delegated token; never embed credentials.\n"
                "F32 viewers need Pro/PPU; F64+ can support free viewers.\n"
                "Never use Publish to web for client or confidential information.\n"
                "Cross-filtering, bookmarks and export remain subject to policy.", 12)
    report.button("guide", "gu_reset", (32, 730, 300, 54), "Overview - all regions", "Bookmark", "overviewAll")
    report.button("guide", "gu_ontario", (348, 730, 300, 54), "Overview - Ontario", "Bookmark", "overviewOntario")
    report.button("guide", "gu_pack", (720, 730, 300, 54), "Open paginated pack", "WebUrl", paginated_url)
    report.button("guide", "gu_embed_docs", (1036, 730, 372, 54), "Secure embedding guidance", "WebUrl",
                  "https://learn.microsoft.com/power-bi/collaborate-share/service-embed-secure")

    report.put("definition/bookmarks/bookmarks.json", {
        "$schema": SCHEMA + "definition/bookmarksMetadata/1.0.0/schema.json",
        "items": [{"name": "overviewAll"}, {"name": "overviewOntario"}],
    })
    for name, title, values in [("overviewAll", "Overview - all regions", None),
                                ("overviewOntario", "Overview - Ontario", ["Ontario"])]:
        state = {"name": "regionPreset", "type": "Categorical", "expression": field("Clients", "Region")}
        if values:
            state["filter"] = categorical("Clients", "Region", values)
        containers = {}
        for visual in report.visuals["executive"]:
            containers[visual["name"]] = {"filters": {"byName": {}}, "singleVisual": {
                "visualType": visual["visual"]["visualType"],
                "objects": {"merge": copy.deepcopy(visual["visual"].get("objects", {}))},
            }}
            if visual["visual"]["visualType"] == "slicer":
                containers[visual["name"]]["singleVisual"]["objects"]["remove"] = [
                    {"object": "general", "property": "filter", "selector": {}}]
        report.put(f"definition/bookmarks/{name}.bookmark.json", {
            "$schema": SCHEMA + "definition/bookmark/1.0.0/schema.json",
            "name": name, "displayName": title,
            "options": {"suppressData": False, "suppressDisplay": True, "suppressActiveSection": False},
            "explorationState": {"version": "1.3", "activeSection": "executive", "sections": {
                "executive": {"filters": {"byName": {"regionPreset": state}}, "visualContainers": containers},
            }},
        })
    return report.parts


def element(parent, name, text=None, **attributes):
    node = ET.SubElement(parent, f"{{{RDL_NS}}}{name}", attributes)
    if text is not None:
        node.text = str(text)
    return node


def textbox(parent, name, value, width, height="0.28in", left=None, top=None, header=False, fmt=None):
    box = element(parent, "Textbox", Name=name)
    element(box, "CanGrow", "true")
    element(box, "KeepTogether", "true")
    paragraph = element(element(box, "Paragraphs"), "Paragraph")
    run = element(element(paragraph, "TextRuns"), "TextRun")
    element(run, "Value", value)
    style = element(run, "Style")
    element(style, "FontFamily", "Segoe UI")
    element(style, "FontSize", "9pt")
    element(style, "Color", "#FFFFFF" if header else INK)
    if header:
        element(style, "FontWeight", "Bold")
    if fmt:
        element(style, "Format", fmt)
    element(paragraph, "Style")
    if top:
        element(box, "Top", top)
    if left:
        element(box, "Left", left)
    element(box, "Height", height)
    element(box, "Width", width)
    style = element(box, "Style")
    border = element(style, "Border")
    element(border, "Style", "Solid")
    element(border, "Color", "#D9E2EA")
    element(style, "BackgroundColor", NAVY if header else "#FFFFFF")
    for side in ("Left", "Right", "Top", "Bottom"):
        element(style, "Padding" + side, "4pt")
    return box


def dataset(parent, name, query, fields, parameters=()):
    ds = element(parent, "DataSet", Name=name)
    fs = element(ds, "Fields")
    for field_name, data_field in fields:
        f = element(fs, "Field", Name=field_name)
        element(f, "DataField", data_field)
    q = element(ds, "Query")
    element(q, "DataSourceName", "ClientAnalytics")
    if parameters:
        ps = element(q, "QueryParameters")
        for parameter in parameters:
            # PBIDATASET binding names omit @; the DAX references retain it.
            p = element(ps, "QueryParameter", Name=parameter)
            element(p, "Value", f"=Parameters!{parameter}.Value")
    element(q, "CommandText", query)
    return ds


def build_paginated(model_id):
    report = ET.Element(f"{{{RDL_NS}}}Report")
    ET.SubElement(report, f"{{{RD_NS}}}ReportUnitType").text = "Inch"
    ET.SubElement(report, f"{{{RD_NS}}}ReportID").text = str(uuid.uuid5(uuid.NAMESPACE_URL, RDL_NAME))
    sources = element(report, "DataSources")
    source = element(sources, "DataSource", Name="ClientAnalytics")
    props = element(source, "ConnectionProperties")
    element(props, "DataProvider", "PBIDATASET")
    element(props, "ConnectString",
            'Data Source=pbiazure://api.powerbi.com/;Identity Provider="https://login.microsoftonline.com/common, '
            'https://analysis.windows.net/powerbi/api, f0b72488-7082-488a-a7e8-eada97bd842d";'
            f"Initial Catalog=sobe_wowvirtualserver-{model_id};Integrated Security=ClaimsToken")
    datasets = element(report, "DataSets")
    dataset(datasets, "Months",
            'EVALUATE SELECTCOLUMNS(SUMMARIZECOLUMNS(\'Calendar\'[Year Month], "Rows", '
            '[Monthly Snapshot Rows]), "Month", \'Calendar\'[Year Month]) ORDER BY [Month] DESC',
            [("Month", "[Month]")])
    dataset(datasets, "Regions",
            'EVALUATE UNION(ROW("Region", "All"), SELECTCOLUMNS(VALUES(\'Advisors\'[Advisor Region]), '
            '"Region", \'Advisors\'[Advisor Region])) ORDER BY [Region]',
            [("Region", "[Region]")])
    query = """EVALUATE
SELECTCOLUMNS(
    SUMMARIZECOLUMNS(
        'Advisors'[Advisor Region], 'Advisors'[Advisor Name],
        'Products'[Product Family], 'Products'[Product Name],
        TREATAS({@Month}, 'Calendar'[Year Month]),
        TREATAS({@Scenario}, 'Targets'[Scenario]),
        FILTER(VALUES('Advisors'[Advisor Region]), @Region = "All" || 'Advisors'[Advisor Region] = @Region),
        "AUM", [Assets Under Management], "Revenue", [Revenue], "Target", [Revenue Target],
        "Variance", [Revenue Variance], "Attainment", [Revenue Attainment]
    ),
    "Region", 'Advisors'[Advisor Region], "Advisor", 'Advisors'[Advisor Name],
    "Product", 'Products'[Product Name], "AUM", [AUM], "Revenue", [Revenue],
    "Target", [Target], "Variance", [Variance], "Attainment", [Attainment]
)
ORDER BY [Region], [Advisor], [Product]"""
    columns = [
        ("Region", "Region", "0.95in", None), ("Advisor", "Advisor", "1.35in", None),
        ("Product", "Product", "1.90in", None), ("AUM", "AUM (CAD)", "1.30in", "#,##0.00;(#,##0.00)"),
        ("Revenue", "Revenue (CAD)", "1.15in", "#,##0.00;(#,##0.00)"),
        ("Target", "Excel target", "1.15in", "#,##0.00;(#,##0.00)"),
        ("Variance", "Variance (CAD)", "1.15in", "#,##0.00;(#,##0.00)"),
        ("Attainment", "Attainment", "0.85in", "0.0%"),
    ]
    dataset(datasets, "Performance", query, [(c[0], f"[{c[0]}]") for c in columns], ("Month", "Region", "Scenario"))
    parameters = element(report, "ReportParameters")
    for name, prompt, default, source_ds, values in [
        ("Month", "Month", "2026-10", "Months", None),
        ("Region", "Advisor region", "All", "Regions", None),
        ("Scenario", "Excel planning scenario", "Plan", None, ["Plan", "Stretch"]),
    ]:
        p = element(parameters, "ReportParameter", Name=name)
        element(p, "DataType", "String")
        element(element(element(p, "DefaultValue"), "Values"), "Value", default)
        element(p, "Prompt", prompt)
        valid = element(p, "ValidValues")
        if source_ds:
            ref = element(valid, "DataSetReference")
            element(ref, "DataSetName", source_ds)
            element(ref, "ValueField", name)
            element(ref, "LabelField", name)
        else:
            pvalues = element(valid, "ParameterValues")
            for value in values:
                v = element(pvalues, "ParameterValue")
                element(v, "Value", value)
                element(v, "Label", value)

    section = element(element(report, "ReportSections"), "ReportSection")
    body = element(section, "Body")
    items = element(body, "ReportItems")
    tablix = element(items, "Tablix", Name="AdvisorPerformance")
    tb = element(tablix, "TablixBody")
    tc = element(tb, "TablixColumns")
    for _, _, width, _ in columns:
        element(element(tc, "TablixColumn"), "Width", width)
    rows = element(tb, "TablixRows")
    for index in range(2):
        row = element(rows, "TablixRow")
        element(row, "Height", "0.35in" if index == 0 else "0.28in")
        cells = element(row, "TablixCells")
        for name, label, width, fmt in columns:
            contents = element(element(cells, "TablixCell"), "CellContents")
            textbox(contents, f"{name}{index}", label if index == 0 else f"=Fields!{name}.Value",
                    width, header=index == 0, fmt=fmt if index else None)
            element(contents[0], "DataElementName", name)
            element(contents[0], "DataElementOutput", "NoOutput" if index == 0 else "Output")
    cols_members = element(element(tablix, "TablixColumnHierarchy"), "TablixMembers")
    for _ in columns:
        element(cols_members, "TablixMember")
    row_members = element(element(tablix, "TablixRowHierarchy"), "TablixMembers")
    header = element(row_members, "TablixMember")
    element(header, "KeepWithGroup", "After")
    element(header, "RepeatOnNewPage", "true")
    element(header, "FixedData", "true")
    detail = element(row_members, "TablixMember")
    element(detail, "Group", Name="Details")
    element(tablix, "DataSetName", "Performance")
    element(tablix, "NoRowsMessage", "No advisor/product data matches these parameters.")
    element(tablix, "KeepTogether", "false")
    element(tablix, "Top", "0in")
    element(tablix, "Left", "0in")
    element(tablix, "Height", "0.63in")
    element(tablix, "Width", "9.8in")
    element(tablix, "DataElementName", "AdvisorPerformance")
    element(tablix, "DataElementOutput", "Output")
    element(body, "Height", "0.7in")
    element(body, "Style")
    element(section, "Width", "9.8in")
    page = element(section, "Page")
    ph = element(page, "PageHeader")
    element(ph, "Height", "0.85in")
    element(ph, "PrintOnFirstPage", "true")
    element(ph, "PrintOnLastPage", "true")
    hi = element(ph, "ReportItems")
    textbox(hi, "Title", "CLIENT ANALYTICS | Advisor Performance Pack", "9.8in", "0.32in", top="0in", header=True)
    textbox(hi, "Parameters",
            '="SYNTHETIC DATA | CAD | Month: " & Parameters!Month.Value & " | Region: " & Parameters!Region.Value '
            '& " | Scenario: " & Parameters!Scenario.Value', "9.8in", top="0.36in")
    pf = element(page, "PageFooter")
    element(pf, "Height", "0.65in")
    element(pf, "PrintOnFirstPage", "true")
    element(pf, "PrintOnLastPage", "true")
    fi = element(pf, "ReportItems")
    textbox(fi, "Notes", "Month-end AUM is not additive across months. Targets originate from Excel.", "7.4in", top="0in")
    textbox(fi, "Pages", '="Page " & Globals!PageNumber & " of " & Globals!TotalPages',
            "2.2in", left="7.6in", top="0in")
    for name, value in [("PageHeight", "8.5in"), ("PageWidth", "11in"), ("LeftMargin", "0.5in"),
                        ("RightMargin", "0.5in"), ("TopMargin", "0.4in"), ("BottomMargin", "0.4in")]:
        element(page, name, value)
    element(page, "Style")
    ET.indent(report, space="  ")
    return ET.tostring(report, encoding="utf-8", xml_declaration=True)


def envelope(parts, name, description, fmt):
    return {
        "displayName": name, "description": description,
        "definition": {"format": fmt, "parts": [
            {"path": path, "payloadType": "InlineBase64", "payload": base64.b64encode(content).decode()}
            for path, content in parts.items()
        ]},
    }


def build(before, model_id, paginated_url):
    database = json.loads(base64.b64decode(next(p["payload"] for p in before["definition"]["parts"]
                                               if p["path"] == "model.bim")))
    contract = json.loads((ROOT.parent / "data" / "data_contract.json").read_text(encoding="utf-8-sig"))
    _, layout = organize(before, contract)
    parts = build_interactive(database, model_id, paginated_url, layout)
    return parts, build_paginated(model_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--paginated-url", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8-sig"))
    parts, rdl = build(before, args.model_id, args.paginated_url)
    encoded = {}
    for path, document in parts.items():
        target = args.output / "ClientAnalytics.Report" / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded[path] = json.dumps(document, indent=2).encode("utf-8")
        target.write_bytes(encoded[path])
    (args.output / f"{RDL_NAME}.rdl").write_bytes(rdl)
    requests = {
        "interactive_request.json": envelope(encoded, REPORT_NAME,
            "Synthetic client analytics: cross-source insights, drill-through, planning, bookmarks and solution guidance.", "PBIR"),
        "paginated_request.json": envelope({f"{RDL_NAME}.rdl": rdl}, RDL_NAME,
            "Parameterized advisor/product performance with Excel targets, repeated headers and complete detail export.",
            "PaginatedReportDefinition"),
    }
    for name, content in requests.items():
        (args.output / name).write_text(json.dumps(content, indent=2), encoding="utf-8")
    print(json.dumps({"pages": len(PAGES), "visuals": sum(p.endswith("/visual.json") for p in parts),
                      "bookmarks": 2, "reportParts": len(parts), "rdlBytes": len(rdl)}))


if __name__ == "__main__":
    main()
