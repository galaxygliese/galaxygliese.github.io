--[[
crossref.lua: global equation / figure / section numbering for LaTeX posts.

KaTeX renders each formula on its own, so its equation counter restarts at 1
for every display. This filter numbers equations across the whole post instead:

  * equation, align, gather, multline (unstarred) and labelled \[...\] get \tag{n}
  * \nonumber / \notag rows are skipped
  * \label{x} becomes an anchor <span id="x">; \ref{x} -> "n", \eqref{x} -> "(n)"
  * figures / tables are numbered "Figure n." / "Table n."; \ref to a section shows its title
  * \autoref{x} -> "Figure n", "Table n", "Equation (n)"
]]

local eq_num, fig_num, tab_num = 0, 0, 0
local labels = {}      -- label -> text shown by \ref
local kinds = {}       -- label -> "Equation" | "Figure" | "Table" | "Section" (for \autoref)

local function trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

-- Split an environment body on top-level "\\" (ignores \\ inside nested
-- environments or braces, e.g. matrices).
local function split_rows(body)
  local rows, depth, start, i, n = {}, 0, 1, 1, #body
  while i <= n do
    local c = body:sub(i, i)
    if c == "{" then depth = depth + 1; i = i + 1
    elseif c == "}" then depth = depth - 1; i = i + 1
    elseif c == "\\" then
      if body:sub(i, i + 6) == "\\begin{" then depth = depth + 1; i = i + 7
      elseif body:sub(i, i + 4) == "\\end{" then depth = depth - 1; i = i + 5
      elseif body:sub(i + 1, i + 1) == "\\" and depth == 0 then
        rows[#rows + 1] = body:sub(start, i - 1); i = i + 2; start = i
      else i = i + 2 end
    else i = i + 1 end
  end
  rows[#rows + 1] = body:sub(start)
  return rows
end

-- Number one row: strip \label / \nonumber, return new text and its labels.
local function number_row(row, numbered, ids)
  local found = {}
  row = row:gsub("\\label%s*{([^}]*)}", function(l) found[#found + 1] = l; return "" end)
  local skip = false
  row = row:gsub("\\nonumber", function() skip = true; return "" end)
  row = row:gsub("\\notag", function() skip = true; return "" end)
  if row:find("\\tag") then skip = true end            -- author set it manually
  if numbered and not skip and trim(row) ~= "" then
    eq_num = eq_num + 1
    for _, l in ipairs(found) do labels[l] = tostring(eq_num); kinds[l] = "Equation"; ids[#ids + 1] = l end
    row = row .. " \\tag{" .. eq_num .. "}"
  end
  return row
end

local MULTI = { align = "align*", gather = "gather*", alignat = "alignat*", flalign = "flalign*" }

local function process_math(m)
  if m.mathtype ~= "DisplayMath" then return nil end
  local t = trim(m.text)
  local ids = {}
  local env, body = t:match("^\\begin{(%a+%*?)}(.*)\\end{%a+%*?}$")
  local text
  if env == "equation" or env == "multline" then
    text = number_row(body, true, ids)
  elseif env == "equation*" or env == "multline*" then
    text = number_row(body, false, ids)
  elseif env and MULTI[env] then
    local args = ""
    if env == "alignat" then args, body = body:match("^(%s*{[^}]*})(.*)$") end
    local rows = split_rows(body)
    for k, r in ipairs(rows) do rows[k] = number_row(r, true, ids) end
    text = "\\begin{" .. MULTI[env] .. "}" .. args .. table.concat(rows, "\\\\") .. "\\end{" .. MULTI[env] .. "}"
  elseif env == nil then
    -- \[ ... \]: numbered only if it carries a \label
    text = number_row(t, t:find("\\label") ~= nil, ids)
  else
    return nil   -- align*, gather*, ... left untouched
  end
  local out = pandoc.Math("DisplayMath", text)
  for _, id in ipairs(ids) do out = pandoc.Span({ out }, pandoc.Attr(id)) end
  return out
end

local function process_figure(fig)
  fig_num = fig_num + 1
  if fig.identifier ~= "" then labels[fig.identifier] = tostring(fig_num); kinds[fig.identifier] = "Figure" end
  local prefix = pandoc.Strong({ pandoc.Str("Figure " .. fig_num .. ".") })
  if #fig.caption.long > 0 and fig.caption.long[1].content then
    fig.caption.long[1].content:insert(1, pandoc.Space())
    fig.caption.long[1].content:insert(1, prefix)
  end
  return fig
end

local function process_table(tbl)
  local first = tbl.caption.long[1]
  if not first then return nil end             -- like LaTeX: only captioned tables are numbered
  tab_num = tab_num + 1
  local prefix = pandoc.Strong({ pandoc.Str("Table " .. tab_num .. ".") })
  if first.content then
    first.content:insert(1, pandoc.Space()); first.content:insert(1, prefix)
  end
  if tbl.identifier ~= "" then labels[tbl.identifier] = tostring(tab_num); kinds[tbl.identifier] = "Table" end
  return tbl
end

-- pandoc puts a table's \label on a Div around it (Div is visited after its Table).
local function process_div(div)
  local t = div.content[1]
  if div.identifier ~= "" and t and t.t == "Table" and #div.content == 1 then
    labels[div.identifier] = tostring(tab_num); kinds[div.identifier] = "Table"
  end
end

local function process_header(h)
  if h.identifier ~= "" then labels[h.identifier] = pandoc.utils.stringify(h.content); kinds[h.identifier] = "Section" end
end

local function process_link(link)
  local kind = link.attributes["reference-type"]
  local ref = link.attributes["reference"]
  if not kind or not ref then return nil end
  local txt = labels[ref]
  if not txt then
    io.stderr:write("crossref: undefined reference '" .. ref .. "'\n")
    return nil
  end
  local k = kinds[ref]
  if kind == "eqref" then txt = "(" .. txt .. ")"
  elseif kind == "ref+label" and k and k ~= "Section" then
    txt = k .. " " .. (k == "Equation" and "(" .. txt .. ")" or txt)
  end
  link.content = { pandoc.Str(txt) }
  link.attributes["reference-type"] = nil
  link.attributes["reference"] = nil
  return link
end

-- \includesvg{figs/x} and \includegraphics{figs/x} leave out the extension.
-- Browsers need it, so look for the file next to index.tex (pandoc runs there).
local EXTS = { ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp" }
local function exists(p) local f = io.open(p, "r"); if f then f:close() return true end end
local function process_image(img)
  if img.src:match("^%a+://") or img.src:match("%.%w+$") then
    if img.src:match("%.pdf$") then
      io.stderr:write("crossref: browsers cannot show PDF images ('" .. img.src .. "'); use SVG or PNG\n")
    end
    return nil
  end
  for _, e in ipairs(EXTS) do
    if exists(img.src .. e) then img.src = img.src .. e; return img end
  end
  io.stderr:write("crossref: image not found '" .. img.src .. "' (tried .svg/.png/.jpg)\n")
end

-- \definecolor{name}{HTML|rgb|RGB}{...} in index.tex -> CSS colours for \textcolor / \colorbox
local colors = {}
local function read_colors()
  local f = io.open("index.tex", "r"); if not f then return end
  local tex = f:read("a"); f:close()
  for name, model, v in tex:gmatch("\\definecolor%s*{([%w%-_]+)}%s*{(%a+)}%s*{([^}]*)}") do
    if model == "HTML" then colors[name] = "#" .. v
    elseif model == "RGB" or model == "rgb" then
      local c = {}
      for x in v:gmatch("[%d%.]+") do c[#c + 1] = model == "rgb" and math.floor(tonumber(x) * 255 + .5) or tonumber(x) end
      if #c == 3 then colors[name] = string.format("rgb(%d,%d,%d)", c[1], c[2], c[3]) end
    end
  end
end

local function process_span(span)
  local st = span.attributes.style
  if not st then return nil end
  span.attributes.style = st:gsub("(color:%s*)([%w%-_]+)", function(k, name) return k .. (colors[name] or name) end)
  return span
end

function Pandoc(doc)
  read_colors()
  doc = doc:walk({ Math = process_math, Figure = process_figure, Header = process_header, Image = process_image,
                    Table = process_table, Div = process_div, Span = process_span })
  return doc:walk({ Link = process_link })
end
