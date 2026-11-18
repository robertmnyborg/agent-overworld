-- Quick capture: ctrl+alt+cmd+N opens a prompt and sends the note to the Agent Overworld server,
-- which continues the tab that owns a Slack thread or starts a new Claude session that files itself.
-- Server: ~/Projects/agent-overworld/server.py (/api/capture).
require("hs.ipc")  -- lets `hs -c` call capture functions from a shell, for testing
hs.autoLaunch(true)
hs.menuIcon(false)

local CAPTURE_URL = "http://127.0.0.1:7717/api/capture"
local SHOTS = os.getenv("HOME") .. "/.overworld/captures/"
local lastClip = hs.pasteboard.changeCount()

-- Clipboard image (Snagit copy, cmd+ctrl+shift+4, etc.) -> PNG path, or nil.
function saveClipImage()
  local img = hs.pasteboard.readImage()
  if not img then return nil end
  hs.fs.mkdir(SHOTS)
  local path = SHOTS .. os.date("%Y-%m-%d-%H%M%S") .. ".png"
  if not img:saveToFile(path) then return nil end
  return path
end

-- Confirmation: an instant "received" alert, then where it went (alert + a macOS notification that stays in Notification Center).
function sendCapture(text)
  local got = hs.alert.show("Capture received, finding where it belongs…", 30)
  hs.http.asyncPost(CAPTURE_URL, hs.json.encode({text = text}), {["Content-Type"] = "application/json"}, function(status, body)
    hs.alert.closeSpecific(got)
    if status == 200 then
      local msg = hs.json.decode(body).message
      hs.alert.show("✓ " .. msg, 8)
      hs.notify.new({title = "Capture filed", informativeText = msg, withdrawAfter = 0}):send()
    elseif status < 0 then
      hs.alert.show("Capture failed: Overworld server is not running (open a cmux tab to start it)", 5)
    else
      hs.alert.show("Capture failed (" .. status .. "): " .. (body or ""), 5)
    end
  end)
end

local SLACK = "com.tinyspeck.slackmacgap"

-- Slack in front: right-click the message under the mouse, press L (Copy link), wait for the clipboard.
-- Calls done(link) with the copied permalink, or done(nil) if nothing was copied (mouse not over a message).
-- Needs Accessibility for Hammerspoon (it posts the click and the key).
function hoverCopyLink(done)
  local before = hs.pasteboard.changeCount()
  hs.eventtap.rightClick(hs.mouse.absolutePosition())
  hs.timer.doAfter(0.35, function()
    hs.eventtap.keyStroke({}, "l", 0)
    hs.timer.doAfter(0.6, function()
      local clip = hs.pasteboard.getContents() or ""
      if hs.pasteboard.changeCount() ~= before and clip:match("^https://[%w%-]+%.slack%.com/archives/%S+$") then
        done(clip)
      else
        hs.eventtap.keyStroke({}, "escape", 0)  -- close the menu if it opened but L did nothing
        done(nil)
      end
    end)
  end)
end

-- Capture box (a webview, because hs.dialog.textPrompt is one line). A link from the clipboard or Slack shows as a chip above
-- the note (× drops it). Enter sends, Shift+Enter adds a line, Esc cancels. Drag the header to move, the corner grip to resize.
local CAPTURE_HTML = [[<!doctype html><meta charset="utf-8"><style>
:root{--bg:#f7f7f8;--panel:#fff;--text:#1d1d1f;--muted:#86868b;--line:#d9d9de;--chip:#eef0f4;--accent:#0a66d8}
@media(prefers-color-scheme:dark){:root{--bg:#232326;--panel:#1b1b1d;--text:#f2f2f4;--muted:#8e8e93;--line:#3a3a3e;--chip:#2e2f34;--accent:#4a9bff}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font:14px/1.45 -apple-system,BlinkMacSystemFont,sans-serif;background:var(--bg);color:var(--text);display:flex;flex-direction:column;overflow:hidden}
#head{height:32px;flex:none;padding:0 14px 0 82px;margin-bottom:10px;background:var(--panel);border-bottom:1px solid var(--line);color:var(--muted);font-size:12px;cursor:grab;-webkit-user-select:none;user-select:none;display:flex;gap:8px;align-items:center}
#head:active{cursor:grabbing}#head .dots{letter-spacing:2px;opacity:.6}
#chips{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px}#chips:empty{display:none}
.chip{display:inline-flex;align-items:center;gap:6px;max-width:100%;background:var(--chip);border-radius:6px;padding:3px 4px 3px 8px;font-size:12px}
.chip b{font-weight:600}.chip span{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.chip button{border:0;background:none;color:var(--muted);font-size:14px;line-height:1;padding:0 4px;cursor:pointer}.chip button:hover{color:var(--text)}
#wrap{flex:1;display:flex;padding:8px 14px 0;min-height:0}
textarea{flex:1;width:100%;font:15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;color:var(--text);background:var(--panel);padding:10px 12px;
 border:1px solid var(--line);border-radius:8px;resize:none;outline:none;white-space:pre-wrap;overflow-wrap:break-word;word-break:normal}
textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 20%,transparent)}
textarea::placeholder{color:var(--muted)}
#bar{display:flex;gap:8px;align-items:center;padding:10px 14px 12px}
#bar .keys{flex:1;color:var(--muted);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
kbd{font:inherit;border:1px solid var(--line);border-radius:4px;padding:0 4px}
button.b{font:13px -apple-system,sans-serif;padding:5px 14px;border-radius:6px;border:1px solid var(--line);background:var(--panel);color:var(--text);cursor:pointer}
button.b.primary{background:var(--accent);border-color:var(--accent);color:#fff}
#grip{position:fixed;right:0;bottom:0;width:16px;height:16px;cursor:nwse-resize;
 background:linear-gradient(135deg,transparent 50%,var(--muted) 50%,var(--muted) 56%,transparent 56%,transparent 70%,var(--muted) 70%,var(--muted) 76%,transparent 76%);opacity:.6}
</style>
<div id="head"><span class="dots">⋮⋮</span><span id="hint"></span></div>
<div id="chips"></div>
<div id="wrap"><textarea id="t" spellcheck="true" placeholder="What should happen? (optional when a link is attached)"></textarea></div>
<div id="bar"><span class="keys"><kbd>↵</kbd> send · <kbd>⇧↵</kbd> new line · <kbd>esc</kbd> cancel</span>
<button class="b" id="c">Cancel</button><button class="b primary" id="s">Send</button></div>
<div id="grip" title="Drag to resize"></div>
<script>
const t=document.getElementById('t'),msg=o=>webkit.messageHandlers.capture.postMessage(o),post=(b,v)=>msg({button:b,text:v});
const init=__INIT__;document.getElementById('hint').textContent=init.hint;t.value=init.note;
let link=init.link;const chips=document.getElementById('chips');
function chip(label,detail,onX){const c=document.createElement('div');c.className='chip';const b=document.createElement('b');b.textContent=label;
 const d=document.createElement('span');d.textContent=detail;d.title=detail;c.append(b,d);
 if(onX){const x=document.createElement('button');x.textContent='×';x.title='Remove';x.onclick=()=>{onX();c.remove();t.focus()};c.append(x)}chips.append(c)}
if(link){const m=link.match(/slack\.com\/archives\/([^/]+)/);chip(m?'Slack message':'Link',m?m[1]:link.replace(/^https?:\/\//,''),()=>{link=''})}
if(init.shot)chip('Screenshot','attached',null);
const text=()=>[link,t.value.trim()].filter(Boolean).join(' ');
t.focus();t.setSelectionRange(t.value.length,t.value.length);
document.getElementById('s').onclick=()=>post('Send',text());document.getElementById('c').onclick=()=>post('Cancel','');
// Header drags the window, the corner grip resizes it. Lua moves/sizes the window; screen coordinates stay absolute meanwhile.
let drag=null,raf=0;
const start=kind=>e=>{drag={kind,x:e.screenX,y:e.screenY};post('grab','');e.preventDefault()};
document.getElementById('head').addEventListener('mousedown',start('move'));
document.getElementById('grip').addEventListener('mousedown',start('size'));
addEventListener('mousemove',e=>{if(!drag||raf)return;const dx=e.screenX-drag.x,dy=e.screenY-drag.y,k=drag.kind;raf=requestAnimationFrame(()=>{raf=0;msg({button:k,dx,dy})})});
addEventListener('mouseup',()=>{if(drag){drag=null;post('drop','')}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();post('Cancel','')}
 else if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();post('Send',text())}});
</script>]]

captureView = nil  -- global so `hs -c` can inspect it

-- The box opens where you last left it (position and size), if that spot is still on a screen.
local function savedFrame()
  local f = hs.settings.get("capture.frame")
  if f then
    for _, sc in ipairs(hs.screen.allScreens()) do
      local s = sc:frame()
      if f.x >= s.x and f.y >= s.y and f.x < s.x + s.w - 40 and f.y < s.y + s.h - 40 then f.saved = true; return f end
    end
  end
  local screen = hs.screen.mainScreen():frame()
  local w, h = 600, 260
  return {x = screen.x + (screen.w - w) / 2, y = screen.y + screen.h * 0.22, w = w, h = h}
end

local function rememberFrame()
  if not captureView then return end
  local f = captureView:frame()
  hs.settings.set("capture.frame", {x = f.x, y = f.y, w = f.w, h = f.h})
end

local function prompt(prefill, shot, hint)
  if captureView then captureView:delete(); captureView = nil end
  local frame = savedFrame()
  local grabAt = nil
  local uc = hs.webview.usercontent.new("capture")
  uc:setCallback(function(msg)
    local button, text = msg.body.button, msg.body.text or ""
    if button == "grab" then grabAt = captureView and captureView:frame(); return end
    if button == "move" then
      if grabAt and captureView then captureView:topLeft({x = grabAt.x + msg.body.dx, y = grabAt.y + msg.body.dy}) end
      return
    end
    if button == "size" then
      if grabAt and captureView then
        captureView:frame({x = grabAt.x, y = grabAt.y, w = math.max(420, grabAt.w + msg.body.dx), h = math.max(200, grabAt.h + msg.body.dy)})
      end
      return
    end
    if button == "drop" then grabAt = nil; rememberFrame(); return end
    rememberFrame()
    if captureView then captureView:delete(); captureView = nil end
    lastClip = hs.pasteboard.changeCount()
    if button ~= "Send" then return end
    if shot then text = text .. "\nScreenshot: " .. shot end
    if text:match("^%s*$") then return end
    sendCapture(text)
  end)
  local link, note = (prefill or ""):match("^%s*(https?://%S+)%s*(.-)%s*$")
  local init = hs.json.encode({link = link or "", note = link and note or (prefill or ""), shot = shot ~= nil, hint = hint or ""})
  captureView = hs.webview.new(frame, {developerExtrasEnabled = false}, uc)
    :windowStyle({"titled", "closable", "resizable", "fullSizeContentView"})  -- page draws under the title bar: one solid header
    :windowTitle("")
    :allowTextEntry(true)
    :level(hs.drawing.windowLevels.modalPanel)
    :closeOnEscape(false)
    :deleteOnClose(true)
    :windowCallback(function(action) if action == "closing" then captureView = nil end end)
    :html((CAPTURE_HTML:gsub("__INIT__", function() return init end)))
  if frame.saved then captureView:frame(frame) end  -- saved = window frame (title bar included); new() took it as content size
  hs.focus()
  captureView:show():bringToFront(true)
  hs.timer.doAfter(0.05, function()
    local win = captureView and captureView:hswindow()
    if win then win:focus() end
  end)
end

capturePrompt = prompt  -- global so `hs -c` can open the box for testing

hs.hotkey.bind({"ctrl", "alt", "cmd"}, "N", function()
  -- Use the clipboard only when it changed since the last capture, so an old link or image is never attached twice.
  local prefill, shot, hint = "", nil, "New capture: a note, a link, or both"
  if hs.pasteboard.changeCount() ~= lastClip then
    shot = saveClipImage()
    local clip = hs.pasteboard.getContents() or ""
    if shot then
      hint = "New capture"
    elseif clip:match("^https?://%S+$") then
      prefill = clip .. " "
    end
  end
  local front = hs.application.frontmostApplication()
  if prefill == "" and front and front:bundleID() == SLACK then
    if not hs.accessibilityState() then
      hs.accessibilityState(true)  -- opens the macOS prompt
      hs.alert.show("Allow Hammerspoon in Accessibility, then press the hotkey again", 5)
      return
    end
    hoverCopyLink(function(link)
      if link then
        prompt(link .. " ", shot, "New capture")
      else
        prompt(prefill, shot, "No Slack message under the mouse. New capture: a note, a link, or both")
      end
    end)
    return
  end
  prompt(prefill, shot, hint)
end)
