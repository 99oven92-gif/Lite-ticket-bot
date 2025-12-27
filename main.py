import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import io
from datetime import datetime

# --- 데이터베이스 설정 ---
conn = sqlite3.connect('ticket_system.db')
cur = conn.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, main TEXT, sub TEXT)')
cur.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)')
cur.execute('CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY)')
conn.commit()

class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # 슬래시 명령어 동기화
        await self.tree.sync()

bot = TicketBot()

# --- UI 컴포넌트: 하위 카테고리 선택 ---
class SubCategorySelect(discord.ui.Select):
    def __init__(self, main_cat, subs):
        options = [discord.SelectOption(label=s, value=s) for s in subs]
        super().__init__(placeholder=f"{main_cat}의 세부 항목을 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        await create_ticket_channel(interaction, self.values[0])

# --- UI 컴포넌트: 대분류 선택 ---
class MainCategorySelect(discord.ui.Select):
    def __init__(self):
        cur.execute("SELECT DISTINCT main FROM categories")
        mains = [row[0] for row in cur.fetchall()]
        if not mains:
            options = [discord.SelectOption(label="등록된 카테고리 없음", value="none")]
        else:
            options = [discord.SelectOption(label=m, value=m) for m in mains]
        super().__init__(placeholder="문의하실 분야를 선택하세요", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("먼저 관리자 명령어로 카테고리를 등록해주세요.", ephemeral=True)
            return

        main_cat = self.values[0]
        cur.execute("SELECT sub FROM categories WHERE main = ? AND sub IS NOT NULL", (main_cat,))
        subs = [row[0] for row in cur.fetchall() if row[0]]

        if subs:
            view = discord.ui.View()
            view.add_item(SubCategorySelect(main_cat, subs))
            await interaction.response.send_message(f"**{main_cat}**의 하위 항목을 선택해주세요.", view=view, ephemeral=True)
        else:
            await create_ticket_channel(interaction, main_cat)

# --- 티켓 채널 생성 로직 ---
async def create_ticket_channel(interaction, category_name):
    guild = interaction.guild
    user = interaction.user
    
    # 채널 생성 (유저 이름과 카테고리 포함)
    channel = await guild.create_text_channel(f"ticket-{category_name}-{user.name}")
    
    # 기본 권한 설정 (모두 차단)
    await channel.set_permissions(guild.default_role, view_channel=False)
    # 유저 권한 설정
    await channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
    
    # 관리자/역할 권한 추가
    cur.execute("SELECT id FROM admins")
    for (admin_id,) in cur.fetchall():
        target = guild.get_role(admin_id) or guild.get_member(admin_id)
        if target:
            await channel.set_permissions(target, view_channel=True, send_messages=True)

    embed = discord.Embed(title="문의 접수", description=f"**{category_name}** 관련 문의입니다.\n관리자가 확인 전까지 문의 내용을 남겨주세요.", color=discord.Color.green())
    view = discord.ui.View(timeout=None)
    close_btn = discord.ui.Button(label="문의 종료", style=discord.ButtonStyle.red, custom_id="ticket_close")
    view.add_item(close_btn)
    
    await channel.send(f"{user.mention}님, 문의가 접수되었습니다.", embed=embed, view=view)
    await interaction.response.send_message(f"티켓이 생성되었습니다: {channel.mention}", ephemeral=True)

# --- 슬래시 명령어 모음 ---

@bot.tree.command(name="셋업", description="티켓 생성용 메인 임베드를 전송합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    cur.execute("SELECT value FROM config WHERE key = 'title'")
    title = cur.fetchone() or ("고객센터 문의하기",)
    cur.execute("SELECT value FROM config WHERE key = 'desc'")
    desc = cur.fetchone() or ("아래 메뉴를 눌러 상담을 시작하세요.",)
    
    embed = discord.Embed(title=title[0], description=desc[0], color=discord.Color.blue())
    view = discord.ui.View(timeout=None)
    view.add_item(MainCategorySelect())
    await interaction.response.send_message("인터페이스를 생성했습니다.", ephemeral=True)
    await interaction.channel.send(embed=embed, view=view)

@bot.tree.command(name="임베드설정", description="인터페이스에 표시될 내용을 수정합니다.")
async def set_embed(interaction: discord.Interaction, 제목: str, 내용: str):
    cur.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('title', ?)", (제목,))
    cur.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('desc', ?)", (내용,))
    conn.commit()
    await interaction.response.send_message("임베드 정보가 업데이트되었습니다.", ephemeral=True)

@bot.tree.command(name="카테고리추가", description="문의 카테고리를 추가합니다. 하위분류는 생략 가능합니다.")
async def add_category(interaction: discord.Interaction, 대분류: str, 하위분류: str = None):
    cur.execute("INSERT INTO categories (main, sub) VALUES (?, ?)", (대분류, 하위분류))
    conn.commit()
    await interaction.response.send_message(f"카테고리 등록 완료: **{대분류}** > **{하위분류 or '없음'}**", ephemeral=True)

@bot.tree.command(name="관리자지정", description="티켓 채널을 볼 수 있는 역할이나 유저를 추가합니다.")
async def add_admin(interaction: discord.Interaction, 대상: discord.Role):
    cur.execute("INSERT OR REPLACE INTO admins (id) VALUES (?)", (대상.id,))
    conn.commit()
    await interaction.response.send_message(f"{대상.mention} 역할이 관리자로 등록되었습니다.", ephemeral=True)

# --- 종료 및 백업 로직 ---
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        cid = interaction.data.get('custom_id')
        
        if cid == "ticket_close":
            # 유저 퇴장 (권한 제거)
            await interaction.channel.set_permissions(interaction.user, overwrite=None)
            
            embed = discord.Embed(title="문의가 종료되었습니다", description="유저는 이제 이 채널을 볼 수 없습니다.\n관련 기록을 저장하고 삭제하려면 아래 버튼을 누르세요.", color=discord.Color.red())
            view = discord.ui.View(timeout=None)
            del_btn = discord.ui.Button(label="채널 백업 및 삭제", style=discord.ButtonStyle.secondary, custom_id="ticket_delete")
            view.add_item(del_btn)
            await interaction.response.send_message(embed=embed, view=view)

        elif cid == "ticket_delete":
            # 로그 백업용 텍스트 생성
            log_str = f"--- Ticket Log: {interaction.channel.name} ---\n"
            async for msg in interaction.channel.history(limit=None, oldest_first=True):
                time = msg.created_at.strftime('%Y-%m-%d %H:%M')
                log_str += f"[{time}] {msg.author}: {msg.content}\n"
            
            # 로그 채널 전송
            log_channel = discord.utils.get(interaction.guild.text_channels, name="티켓-로그")
            if not log_channel:
                log_channel = await interaction.guild.create_text_channel("티켓-로그")
            
            file = discord.File(io.BytesIO(log_str.encode()), filename=f"{interaction.channel.name}.txt")
            await log_channel.send(content=f"📄 **티켓 종료 기록:** `{interaction.channel.name}`", file=file)
            await interaction.channel.delete()

bot.run('MTQ1NDMyNDU4OTEzMDk0NDU4NQ.GVtHox.uUlhWXTdSyakqWU-Ckxtyke1J_8IZ7NFpaG9II')
