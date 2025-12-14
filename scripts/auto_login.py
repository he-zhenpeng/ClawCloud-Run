#!/usr/bin/env python3
"""
ClawCloud 自动登录脚本（使用 GitHub 密码）
功能：使用 GitHub 账号密码自动登录，并通过 Telegram 发送通知和截图
"""

import os
import sys
import time
import json
import requests
from playwright.sync_api import sync_playwright

# ==================== 配置 ====================
CLAW_CLOUD_URL = "https://eu-central-1.run.claw.cloud"
SIGNIN_URL = f"{CLAW_CLOUD_URL}/signin"


class TelegramNotifier:
    """Telegram 通知"""
    
    def __init__(self):
        self.bot_token = os.environ.get('TG_BOT_TOKEN')
        self.chat_id = os.environ.get('TG_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            print("⚠️ Telegram 通知未配置")
    
    def send_message(self, message):
        """发送文本消息"""
        if not self.enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, data=data, timeout=30)
            return response.status_code == 200
        except Exception as e:
            print(f"发送消息失败: {e}")
            return False
    
    def send_photo(self, photo_path, caption=""):
        """发送图片"""
        if not self.enabled or not os.path.exists(photo_path):
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            with open(photo_path, 'rb') as photo:
                data = {"chat_id": self.chat_id, "caption": caption[:1024]}
                files = {"photo": photo}
                response = requests.post(url, data=data, files=files, timeout=60)
            return response.status_code == 200
        except Exception as e:
            print(f"发送图片失败: {e}")
            return False


class AutoLogin:
    """自动登录"""
    
    def __init__(self):
        self.username = os.environ.get('GH_USERNAME')
        self.password = os.environ.get('GH_PASSWORD')
        self.screenshot_count = 0
        self.screenshots = []
        self.telegram = TelegramNotifier()
        self.logs = []
        
    def log(self, message, level="INFO"):
        """打印日志"""
        icons = {
            "INFO": "ℹ️",
            "SUCCESS": "✅", 
            "ERROR": "❌",
            "WARN": "⚠️",
            "STEP": "🔹"
        }
        log_line = f"{icons.get(level, '•')} {message}"
        print(log_line)
        self.logs.append(log_line)
    
    def screenshot(self, page, name):
        """保存截图"""
        self.screenshot_count += 1
        filename = f"{self.screenshot_count:02d}_{name}.png"
        page.screenshot(path=filename)
        self.screenshots.append(filename)
        self.log(f"截图: {filename}")
        return filename
    
    def validate_credentials(self):
        """验证凭据"""
        if not self.username:
            self.log("错误：未设置 GH_USERNAME", "ERROR")
            return False
        if not self.password:
            self.log("错误：未设置 GH_PASSWORD", "ERROR")
            return False
        self.log(f"用户名: {self.username}")
        self.log(f"密码: {'*' * len(self.password)}")
        return True
    
    def find_and_click(self, page, selectors, description="元素"):
        """查找并点击元素"""
        for selector in selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible(timeout=3000):
                    element.click()
                    self.log(f"已点击: {description}", "SUCCESS")
                    return True
            except:
                continue
        return False
    
    def check_github_error(self, page):
        """检查 GitHub 错误"""
        try:
            error_el = page.locator('.flash-error, .flash.flash-error').first
            if error_el.is_visible(timeout=2000):
                return error_el.inner_text()
        except:
            pass
        return None
    
    def check_device_verification(self, page):
        """检查设备验证"""
        url = page.url.lower()
        if 'verified-device' in url or 'device-verification' in url:
            return True
        
        content = page.content().lower()
        keywords = ['verify your device', 'device verification', 'check your email', 'verification code']
        return any(kw in content for kw in keywords)
    
    def check_2fa(self, page):
        """检查两步验证"""
        if 'two-factor' in page.url:
            return True
        try:
            return page.locator('input[name="otp"], input[name="app_otp"]').is_visible(timeout=2000)
        except:
            return False
    
    def login_github(self, page):
        """登录 GitHub"""
        self.log("正在登录 GitHub...", "STEP")
        self.screenshot(page, "github_登录页")
        
        # 输入用户名
        try:
            page.locator('input[name="login"]').fill(self.username)
            self.log("已输入用户名")
        except Exception as e:
            self.log(f"输入用户名失败: {e}", "ERROR")
            return False
        
        # 输入密码
        try:
            page.locator('input[name="password"]').fill(self.password)
            self.log("已输入密码")
        except Exception as e:
            self.log(f"输入密码失败: {e}", "ERROR")
            return False
        
        self.screenshot(page, "github_已填写")
        
        # 点击登录
        try:
            page.locator('input[type="submit"], button[type="submit"]').first.click()
            self.log("已点击登录按钮")
        except Exception as e:
            self.log(f"点击登录失败: {e}", "ERROR")
            return False
        
        # 等待响应
        time.sleep(3)
        page.wait_for_load_state('networkidle', timeout=30000)
        self.screenshot(page, "github_登录后")
        
        current_url = page.url
        self.log(f"当前页面: {current_url}")
        
        # 检查错误
        error = self.check_github_error(page)
        if error:
            self.log(f"GitHub 错误: {error}", "ERROR")
            return False
        
        # 检查设备验证
        if self.check_device_verification(page):
            self.log("需要设备验证！", "ERROR")
            self.log("GitHub 检测到新设备，已发送验证邮件", "WARN")
            self.log("请先手动登录一次完成验证", "WARN")
            self.screenshot(page, "设备验证")
            return False
        
        # 检查两步验证
        if self.check_2fa(page):
            self.log("需要两步验证！", "ERROR")
            self.log("此脚本无法自动处理 2FA", "WARN")
            self.screenshot(page, "两步验证")
            return False
        
        # 检查是否仍在登录页
        if 'github.com/login' in current_url or 'github.com/session' in current_url:
            content = page.content()
            if 'Incorrect username or password' in content:
                self.log("用户名或密码错误！", "ERROR")
                return False
            if 'too many' in content.lower():
                self.log("登录次数过多，已被限制", "ERROR")
                return False
            self.log("仍在登录页面，继续等待...", "WARN")
        
        return True
    
    def handle_oauth(self, page):
        """处理 OAuth 授权"""
        if 'github.com/login/oauth/authorize' in page.url:
            self.log("处理 OAuth 授权...", "STEP")
            self.screenshot(page, "oauth_授权页")
            
            selectors = [
                'button[name="authorize"]',
                'button:has-text("Authorize")',
                '#js-oauth-authorize-btn',
            ]
            self.find_and_click(page, selectors, "授权按钮")
            time.sleep(3)
            page.wait_for_load_state('networkidle', timeout=30000)
        return True
    
    def wait_redirect(self, page, max_wait=45):
        """等待重定向"""
        self.log(f"等待重定向（最多 {max_wait} 秒）...", "STEP")
        
        for i in range(max_wait):
            current_url = page.url
            
            # 成功
            if 'claw.cloud' in current_url and 'signin' not in current_url.lower():
                self.log("成功重定向到 ClawCloud！", "SUCCESS")
                return True
            
            # 失败
            if i > 15 and ('github.com/login' in current_url or 'github.com/session' in current_url):
                self.log("卡在 GitHub 页面", "ERROR")
                return False
            
            # OAuth
            if 'github.com/login/oauth/authorize' in current_url:
                self.handle_oauth(page)
            
            time.sleep(1)
            if i % 10 == 0:
                self.log(f"  等待中... ({i}秒)")
        
        self.log("重定向超时", "ERROR")
        return False
    
    def verify_login(self, page, context):
        """验证登录"""
        current_url = page.url
        self.log(f"最终页面: {current_url}")
        self.log(f"页面标题: {page.title()}")
        
        if 'claw.cloud' not in current_url:
            self.log("不在 ClawCloud！", "ERROR")
            return False
        
        if 'signin' in current_url.lower():
            self.log("仍在登录页！", "ERROR")
            return False
        
        # 获取 cookies
        cookies = context.cookies()
        claw_cookies = [c for c in cookies if 'claw' in c.get('domain', '')]
        
        if not claw_cookies:
            self.log("未获取到 cookies！", "ERROR")
            return False
        
        self.log(f"获取到 {len(claw_cookies)} 个 cookies", "SUCCESS")
        
        with open('cookies.json', 'w') as f:
            json.dump(claw_cookies, f, indent=2)
        
        return True
    
    def keepalive(self, page):
        """保持活跃"""
        self.log("访问页面保持活跃...", "STEP")
        
        pages = [
            (f"{CLAW_CLOUD_URL}/", "控制台"),
            (f"{CLAW_CLOUD_URL}/apps", "应用"),
        ]
        
        for url, name in pages:
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state('networkidle', timeout=15000)
                
                if 'signin' in page.url.lower():
                    self.log(f"访问 {name} 被重定向到登录页！", "ERROR")
                    return False
                
                self.log(f"已访问: {name}", "SUCCESS")
                time.sleep(2)
            except Exception as e:
                self.log(f"访问 {name} 失败: {e}", "WARN")
        
        self.screenshot(page, "保活完成")
        return True
    
    def send_notification(self, success, error_msg=""):
        """发送通知"""
        if not self.telegram.enabled:
            return
        
        status = "✅ 成功" if success else "❌ 失败"
        
        message = f"""<b>🤖 ClawCloud 自动登录</b>

<b>状态:</b> {status}
<b>用户:</b> {self.username}
<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"""
        
        if error_msg:
            message += f"\n<b>错误:</b> {error_msg}"
        
        # 最近日志
        recent = self.logs[-8:]
        if recent:
            message += "\n\n<b>日志:</b>\n" + "\n".join(recent)
        
        self.telegram.send_message(message)
        
        # 发送截图
        if self.screenshots:
            # 失败时发送所有截图
            if not success:
                for ss in self.screenshots:
                    self.telegram.send_photo(ss, ss)
            else:
                # 成功时只发最后一张
                self.telegram.send_photo(self.screenshots[-1], "最终截图")
    
    def run(self):
        """主流程"""
        print("\n" + "="*50)
        print("🚀 ClawCloud 自动登录")
        print("="*50 + "\n")
        
        if not self.validate_credentials():
            self.send_notification(False, "凭据未配置")
            sys.exit(1)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            )
            
            page = context.new_page()
            
            try:
                # 步骤1: 访问 ClawCloud
                self.log("步骤1: 打开 ClawCloud", "STEP")
                page.goto(SIGNIN_URL, timeout=60000)
                page.wait_for_load_state('networkidle', timeout=30000)
                time.sleep(2)
                self.screenshot(page, "clawcloud_首页")
                
                # 已登录检查
                if 'signin' not in page.url.lower():
                    self.log("已经登录！", "SUCCESS")
                    if self.verify_login(page, context):
                        self.keepalive(page)
                        self.send_notification(True)
                        print("\n✅ 成功！\n")
                        return
                
                # 步骤2: 点击 GitHub 登录
                self.log("步骤2: 点击 GitHub 登录", "STEP")
                
                selectors = [
                    'button:has-text("GitHub")',
                    'a:has-text("GitHub")',
                    'button:has-text("Continue with GitHub")',
                    '[data-provider="github"]',
                ]
                
                if not self.find_and_click(page, selectors, "GitHub 按钮"):
                    self.log("找不到 GitHub 按钮", "ERROR")
                    self.screenshot(page, "找不到按钮")
                    self.send_notification(False, "找不到 GitHub 登录按钮")
                    sys.exit(1)
                
                time.sleep(3)
                page.wait_for_load_state('networkidle', timeout=30000)
                self.screenshot(page, "点击后")
                
                # 步骤3: GitHub 登录
                self.log("步骤3: GitHub 登录", "STEP")
                
                if 'github.com/login' in page.url or 'github.com/session' in page.url:
                    if not self.login_github(page):
                        self.screenshot(page, "登录失败")
                        self.send_notification(False, "GitHub 登录失败")
                        print("\n❌ GitHub 登录失败！\n")
                        sys.exit(1)
                
                # 步骤4: 等待重定向
                self.log("步骤4: 等待重定向", "STEP")
                
                if not self.wait_redirect(page):
                    self.screenshot(page, "重定向失败")
                    self.send_notification(False, "重定向失败")
                    print("\n❌ 重定向失败！\n")
                    sys.exit(1)
                
                self.screenshot(page, "重定向成功")
                
                # 步骤5: 验证登录
                self.log("步骤5: 验证登录", "STEP")
                
                if not self.verify_login(page, context):
                    self.screenshot(page, "验证失败")
                    self.send_notification(False, "验证失败")
                    print("\n❌ 验证失败！\n")
                    sys.exit(1)
                
                # 步骤6: 保活
                self.log("步骤6: 保活", "STEP")
                self.keepalive(page)
                
                self.send_notification(True)
                
                print("\n" + "="*50)
                print("✅ 自动登录成功！")
                print("="*50 + "\n")
                
            except Exception as e:
                self.log(f"异常: {e}", "ERROR")
                self.screenshot(page, "异常")
                import traceback
                traceback.print_exc()
                self.send_notification(False, str(e))
                sys.exit(1)
            
            finally:
                browser.close()


if __name__ == "__main__":
    login = AutoLogin()
    login.run()
