-- Live input display: run with a generated three-track cartridge and UniBIOS 4.0.
-- mame aes ngjb -bios unibios40 -hashpath hash -rompath . -video none -sound none
--   -nothrottle -autoboot_delay 0 -autoboot_script input_monitor.lua
-- Checks actual FIX cells through the video port and restores its address before resuming.
if _G.input_monitor then return end
_G.input_monitor = true
local m = manager.machine
local mem = m.devices[":maincpu"].spaces["program"]
local F = {}
for _,p in pairs(m.ioport.ports) do for name,f in pairs(p.fields) do F[name]=f end end
local fields = {"P1 Up", "P1 Down", "P1 Left", "P1 Right", "P1 A", "P1 B", "P1 C", "P1 D",
                F["P1 Start"] and "P1 Start" or "1 Player Start",
                F["P1 Select"] and "P1 Select" or "1 Player Select"}
for _,name in ipairs(fields) do assert(F[name], "Missing input: " .. name) end
local n,pass,fail,last_addr = 0,0,0,0
_G.input_monitor_addr = mem:install_write_tap(0x3c0000,0x3c0001,"input_monitor_addr",function(_,data,mask)
  last_addr = (last_addr & (~mask & 0xffff)) | (data & mask)
end)
local Q = {}
local function at(f,fn) Q[f]=Q[f] or {};table.insert(Q[f],fn) end
local function key(i,v) F[fields[i]]:set_value(v) end
local function pulse(i,f,len)
  at(f,function() key(i,1) end);at(f+(len or 20),function() key(i,0) end)
end
local function check(c,label)
  if c then pass=pass+1 else fail=fail+1 end
  print((c and "PASS " or "FAIL ") .. label)
end
local widths = {1,1,1,1,1,1,1,1,3,4}
local function cells()
  local result,save = {},last_addr
  for col=2,16 do
    mem:write_u16(0x3c0000,0x7000+col*32+29)
    result[#result+1]=mem:read_u16(0x3c0002)
  end
  mem:write_u16(0x3c0000,save)
  return result
end
local function visible(mask,label)
  local a,k = cells(),1
  local first = a[1] & 0xfff
  check(first >= 0xc00 and first+14 <= 0xfff,label..": framed labels present")
  for i,width in ipairs(widths) do
    for _=1,width do
      local expected = (mask & (1 << (i-1))) ~= 0 and 0x4000 or 0x3000
      check((a[k] & 0xf000)==expected and (a[k] & 0xfff)==first+k-1,label..": "..fields[i].." tile "..k)
      k=k+1
    end
  end
end
local function hidden(label)
  local a=cells()
  for _,v in ipairs(a) do check((v & 0xfff)==0x20 or (v & 0xfff)==0xc34,label) end
end
at(550,function() visible(0,"idle") end)
for i=1,8 do
  local f=600+(i-1)*50
  pulse(i,f)
  at(f+10,function() visible(1 << (i-1),"held "..fields[i]) end)
  at(f+35,function() visible(0,"released "..fields[i]) end)
end
pulse(9,1000)
at(1030,function() check(mem:read_u16(0x100068)==1,"START opens full view");hidden("hidden in full view") end)
pulse(9,1040)
at(1050,function() check(mem:read_u16(0x100068)==0,"START returns to list");visible(1 << 8,"START held in list") end)
at(1075,function() visible(0,"START released") end)
pulse(10,1100)
at(1110,function() visible(1 << 9,"SELECT held") end)
at(1135,function() visible(0,"SELECT released");check(mem:read_u16(0x100098)==1,"SELECT retains LOOP action") end)
at(1200,function() mem:write_u16(0x1000f0,0xff00) end)
at(1280,function() check(mem:read_u16(0x1000f2)==1,"screen saver active");hidden("hidden in screen saver") end)
pulse(5,1320,10)
at(1360,function() check(mem:read_u16(0x1000f2)==0,"screen saver wakes");visible(0,"labels return after wake") end)
-- The P2 failure message must still coexist with the input row.
at(1380,function() mem:write_u16(0x10003c,1) end)
pulse(9,1400,6);pulse(9,1440,6)
at(1470,function()
  visible(0,"labels alongside P2 warning")
  local save=last_addr
  mem:write_u16(0x3c0000,0x7000+18*32+29)
  local v=mem:read_u16(0x3c0002)
  mem:write_u16(0x3c0000,save)
  check(v==0x7000+string.byte("P"),"P2 warning kept on the right")
end)
pulse(9,1500,10);pulse(10,1500,10)
local vbl
at(1540,function() vbl=mem:read_u16(0x100062) end)
at(1570,function() check(mem:read_u16(0x100062)==vbl,"UniBIOS menu still opens") end)
pulse(7,1600,6)
at(1660,function() check(mem:read_u16(0x100062)~=vbl,"C exits UniBIOS menu");visible(0,"labels after UniBIOS return") end)
at(1700,function() print(string.format("RESULT pass=%d fail=%d",pass,fail));m:exit() end)
emu.register_frame_done(function()
  n=n+1
  if Q[n] then for _,fn in ipairs(Q[n]) do fn() end end
  if n==570 or n==610 or n==1050 or n==1290 then m.video:snapshot() end
end)
