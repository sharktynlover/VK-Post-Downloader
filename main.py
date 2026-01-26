import os
import re
import argparse
from typing import Optional, List, Tuple
from urllib.parse import urlparse, parse_qs

import requests

from bs4 import BeautifulSoup


def fetch_page(url: str, timeout: int = 10) -> Optional[str]:
	headers = {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
	}
	try:
		resp = requests.get(url, headers=headers, timeout=timeout)
		resp.encoding = resp.apparent_encoding or "utf-8"
		if resp.status_code == 200:
			return resp.text
		print(f"Ошибка HTTP: {resp.status_code}")
	except requests.RequestException as e:
		print(f"Ошибка запроса: {e}")
	return None


def extract_post_text(html: str) -> Optional[str]:
	soup = BeautifulSoup(html, "html.parser")

	selectors = [
		"div.wall_post_text",
		"div.post_text",
		"div._post_content",
		"div.pi_text",
		"div.WallPostText",
	]

	for sel in selectors:
		el = soup.select_one(sel)
		if el and el.get_text(strip=True):
			return el.get_text(separator="\n", strip=True)

	meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
	if meta and meta.get("content"):
		return meta.get("content").strip()

	candidates = soup.find_all(["div", "p"], limit=80)
	best = ""
	for c in candidates:
		text = c.get_text(separator="\n", strip=True)
		if len(text) > len(best):
			best = text
	if best:
		return best

	return None


def extract_from_escaped_json(html: str) -> Optional[str]:
	pattern = re.compile(r'"text"\s*:\s*"(.*?)"', re.DOTALL)
	matches = pattern.findall(html)
	for m in matches:
		try:
			decoded = bytes(m, "utf-8").decode("unicode_escape")
		except Exception:
			decoded = m
		cleaned = BeautifulSoup(decoded, "html.parser").get_text(separator="\n", strip=True)
		if len(cleaned) > 30:
			return cleaned
	return None


def extract_images_from_html(html: str) -> List[str]:
	soup = BeautifulSoup(html, "html.parser")
	urls: List[str] = []
	post_selectors = [
		"div.wall_post_text", "div.post_text", "div._post_content", "div.pi_text",
		"div.post__text", "div.m_post_text", "div.post_message", "div.page_post_text"
	]
	elements = []
	for sel in post_selectors:
		el = soup.select_one(sel)
		if el:
			elements.append(el)
	if not elements:
		elements = [soup]

	for el in elements:
		for img in el.find_all('img'):
			for attr in ('data-src', 'src', 'srcset'):
				val = img.get(attr)
				if not val:
					continue
				if attr == 'srcset':
					parts = [p.strip() for p in val.split(',') if p.strip()]
					if parts:
						candidate = parts[-1].split()[-1]
						val = candidate
				if val.startswith('http'):
					urls.append(val)
		for tag in el.find_all(True, style=True):
			style = tag.get('style') or ''
			m = re.search(r'url\(([^)]+)\)', style)
			if m:
				u = m.group(1).strip('"\'')
				if u.startswith('http'):
					urls.append(u)

	seen = set()
	out: List[str] = []
	for u in urls:
		if u not in seen:
			seen.add(u)
			out.append(u)
	return out


def extract_videos_from_html(html: str) -> List[str]:
	soup = BeautifulSoup(html, "html.parser")
	urls: List[str] = []
	for v in soup.find_all('video'):
		src = v.get('src')
		if src and src.startswith('http'):
			urls.append(src)
		for source in v.find_all('source'):
			s = source.get('src')
			if s and s.startswith('http'):
				urls.append(s)

	for a in soup.find_all('a', href=True):
		href = a['href']
		if href.endswith('.mp4') or '.mp4?' in href:
			if href.startswith('http'):
				urls.append(href)

	mp4_pattern = re.compile(r'https?://[^\s"\']+\.mp4[^\s"\']*')
	for m in mp4_pattern.findall(html):
		urls.append(m)

	seen = set()
	out: List[str] = []
	for u in urls:
		if u not in seen:
			seen.add(u)
			out.append(u)
	return out


def extract_post_text_from_mobile(html: str) -> Optional[str]:
	soup = BeautifulSoup(html, "html.parser")
	selectors = [
		"div.post__text", "div.m_post_text", "div.post_message", "div.pi_text", "div._post_content",
		"div.page_post_text", "div.wall_post_text", "div.post_text"
	]
	for sel in selectors:
		el = soup.select_one(sel)
		if el and el.get_text(strip=True):
			return el.get_text(separator="\n", strip=True)
	return extract_from_escaped_json(html)


def looks_like_site_chrome(text: str) -> bool:
	chrome_indicators = [
		"вконтакте",
		"регистрация",
		"вход",
		"телефон или почта",
		"применяются рекомендательные технологии",
		"©",
		"switch to english",
	]
	low = text.lower()
	matches = sum(1 for k in chrome_indicators if k in low)
	return matches >= 1


def to_mobile_url(url: str) -> str:
	if "m.vk.com" in url or "mobile.vk.com" in url:
		return url
	return url.replace("https://vk.com", "https://m.vk.com").replace("http://vk.com", "http://m.vk.com")


def parse_vk_url(url: str) -> Optional[tuple[str, str]]:
	m = re.search(r'wall(-?\d+)_(\d+)', url)


	if m:
		owner_id = m.group(1)
		post_id = m.group(2)
		return owner_id, post_id
	parsed = urlparse(url)
	qs = parse_qs(parsed.query)
	w = qs.get('w')
	if w:
		m = re.search(r'wall(-?\d+)_(\d+)', w[0])
		if m:
			return m.group(1), m.group(2)
	return None


def fetch_post_via_api(token: str, owner_id: str, post_id: str, api_version: str = "5.131") -> Tuple[Optional[str], List[str]]:
	url = "https://api.vk.com/method/wall.getById"
	params = {"posts": f"{owner_id}_{post_id}", "access_token": token, "v": api_version}
	try:
		r = requests.get(url, params=params, timeout=10)
		data = r.json()
	except Exception as e:
		print(f"API request failed: {e}")
		return None, [], []

	if 'error' in data:
		err = data['error']
		print(f"VK API error: {err.get('error_msg')} (code {err.get('error_code')})")
		return None, []

	resp = data.get('response')
	if not resp:
		return None, [], []
	item = resp[0]
	text = item.get('text') or ''
	if not text and item.get('copy_history'):
		parts = []
		for ch in item.get('copy_history'):
			t = ch.get('text') or ''
			if t:
				parts.append(t)
		text = '\n\n'.join(parts)

	image_urls: List[str] = []
	video_urls: List[str] = []
	if item.get('attachments'):
		for att in item.get('attachments'):
			if att.get('type') == 'photo':
				photo = att.get('photo') or {}
				sizes = photo.get('sizes') or []
				if sizes:
					best = max(sizes, key=lambda s: s.get('width', 0) * s.get('height', 0))
					src = best.get('url') or best.get('src')
					if src:
						image_urls.append(src)
				else:
					src = photo.get('photo_604') or photo.get('photo_800') or photo.get('src')
					if src:
						image_urls.append(src)
			elif att.get('type') == 'video':
				vid = att.get('video') or {}
				files = vid.get('files') or {}
				if isinstance(files, dict) and files:
					for v in files.values():
						if isinstance(v, str) and v.startswith('http'):
							video_urls.append(v)
						elif isinstance(v, dict):
							urlv = v.get('url') or v.get('src')
							if urlv:
								video_urls.append(urlv)
				else:
					player = vid.get('player')
					if player and isinstance(player, str) and player.startswith('http'):
						video_urls.append(player)

	return text or None, image_urls, video_urls
    
def download_images(urls: List[str], out_dir: str = 'output') -> List[str]:
	saved: List[str] = []
	if not urls:
		return saved


	def download_videos(urls: List[str], out_dir: str = 'output') -> List[str]:
		# same logic as download_images
		return download_images(urls, out_dir)
	os.makedirs(out_dir, exist_ok=True)
	for idx, u in enumerate(urls, start=1):
		try:
			r = requests.get(u, stream=True, timeout=15)
			if r.status_code != 200:
				continue
			path = urlparse(u).path
			name = os.path.basename(path)
			if not name:
				name = f'image_{idx}.jpg'
			dest = os.path.join(out_dir, name)
			base, ext = os.path.splitext(dest)
			i = 1
			while os.path.exists(dest):
				dest = f"{base}_{i}{ext or '.jpg'}"
				i += 1
			with open(dest, 'wb') as f:
				for chunk in r.iter_content(1024 * 8):
					if chunk:
						f.write(chunk)
			saved.append(dest)
		except Exception:
			continue
	return saved


def interactive_loop(out_dir: str, token: Optional[str]) -> None:
	"""Run an interactive numbered menu until the user quits."""
	while True:
		print('\nВыберите действие:')
		print('1) Получить текст поста через VK API (только текст, нужен токен)')
		print('2) Получить пост через VK API с изображениями (нужен токен)')
		print(f"3) Установить папку для изображений (текущая: {out_dir})")
		print('4) Выйти')
		choice = input('> ').strip()
		if choice == '1':
			url = input('Введите URL поста ВК (wall...): ').strip()
			if not url:
				print('URL не указан.')
				continue
			parsed = parse_vk_url(url)
			if not parsed:
				print('Не удалось разобрать URL для VK API.')
				continue
			owner_id, post_id = parsed
			if not token:
				token = input('Введите VK access token (или нажмите Enter чтобы отменить): ').strip() or token
			if not token:
				print('Токен не указан, операция отменена.')
				continue
			text, _, _ = fetch_post_via_api(token, owner_id, post_id)
			if text:
				print('\n--- Текст поста (VK API) ---\n')
				print(text)
			else:
				print('Не удалось получить текст через VK API.')
			continue
		if choice == '2':
			url = input('Введите URL поста ВК (wall...): ').strip()
			if not url:
				print('URL не указан.')
				continue
			parsed = parse_vk_url(url)
			if not parsed:
				print('Не удалось разобрать URL для VK API.')
				continue
			owner_id, post_id = parsed
			if not token:
				token = input('Введите VK access token (или нажмите Enter чтобы отменить): ').strip() or token
			if not token:
				print('Токен не указан, операция отменена.')
				continue
			text, image_urls, video_urls = fetch_post_via_api(token, owner_id, post_id)
			if text:
				print('\n--- Текст поста (VK API) ---\n')
				print(text)
			else:
				print('Не удалось получить текст через VK API.')
			if image_urls:
				saved = download_images(image_urls, out_dir)
				if saved:
					print('\n--- Скачанные изображения ---')
					for s in saved:
						print(s)
			if video_urls:
				savedv = download_videos(video_urls, out_dir)
				if savedv:
					print('\n--- Скачанные видео ---')
					for s in savedv:
						print(s)
			continue
		if choice == '3':
			newdir = input('Введите путь к папке для изображений: ').strip()
			if newdir:
				out_dir = newdir
				print(f'Папка для изображений установлена: {out_dir}')
			continue
		if choice == '4' or choice.lower() in ('q', 'quit'):
			print('Выход.')
			break
		print('Неверный выбор, попробуйте снова.')


def main() -> None:
	parser = argparse.ArgumentParser(description='VK post text fetcher')
	parser.add_argument('url', nargs='?', help='VK post URL')
	parser.add_argument('--api', action='store_true', help='Use VK API to fetch post text')
	parser.add_argument('--token', help='VK access token (or set VK_TOKEN env var)')
	parser.add_argument('--out-dir', default='output', help='Directory to save images')
	args = parser.parse_args()

	if args.url or args.api or args.token:
		out_dir = args.out_dir
		token = args.token or os.environ.get('VK_TOKEN')
		if args.url:
			url = args.url
		else:
			try:
				url = input("Введите URL поста ВК (например https://vk.com/wall-...): ").strip()
			except (EOFError, KeyboardInterrupt):
				print('\nПрервано пользователем')
				return
		if not url:
			print("URL не указан.")
			return
		if args.api:
			parsed = parse_vk_url(url)
			if not parsed:
				print("Не удалось разобрать URL для VK API. Убедитесь, что это ссылка на пост (wall...).")
				return
			owner_id, post_id = parsed
			if not token:
				try:
					token = input('Введите VK access token (или экспортируйте VK_TOKEN): ').strip()
				except (EOFError, KeyboardInterrupt):
					print('\nПрервано пользователем')
					return
			if not token:
				print('Токен не указан.')
				return
			text, image_urls, video_urls = fetch_post_via_api(token, owner_id, post_id)
			if text:
				print('\n--- Текст поста (VK API) ---\n')
				print(text)
			else:
				print('Не удалось получить текст через VK API.')
			if image_urls:
				saved = download_images(image_urls, out_dir)
				if saved:
					for s in saved:
						print(s)
			if video_urls:
				savedv = download_videos(video_urls, out_dir)
				if savedv:
					for s in savedv:
						print(s)
			return
		html = fetch_page(url)
		if not html:
			print("Не удалось получить страницу.")
			return
		text = extract_post_text(html)
		img_urls = extract_images_from_html(html)
		vid_urls = extract_videos_from_html(html)
		if text and not looks_like_site_chrome(text):
			print("\n--- Текст поста ---\n")
			print(text)
			if img_urls:
				saved = download_images(img_urls, out_dir)
				if saved:
					for s in saved:
						print(s)
			if vid_urls:
				savedv = download_videos(vid_urls, out_dir)
				if savedv:
					for s in savedv:
						print(s)
			return
		mobile_url = to_mobile_url(url)
		if mobile_url != url:
			mhtml = fetch_page(mobile_url)
			if mhtml:
				mtext = extract_post_text_from_mobile(mhtml)
				if mtext and not looks_like_site_chrome(mtext):
					print("\n--- Текст поста (mobile) ---\n")
					print(mtext)
					m_img_urls = extract_images_from_html(mhtml)
					m_vid_urls = extract_videos_from_html(mhtml)
					if m_img_urls:
						saved = download_images(m_img_urls, out_dir)
						if saved:
							for s in saved:
								print(s)
					if m_vid_urls:
						savedv = download_videos(m_vid_urls, out_dir)
						if savedv:
							for s in savedv:
								print(s)
					return
		for candidate in (locals().get('mhtml'), html):
			if not candidate:
				continue
			jtext = extract_from_escaped_json(candidate)
			jimgs = extract_images_from_html(candidate)
			jvids = extract_videos_from_html(candidate)
			if jtext and not looks_like_site_chrome(jtext):
				print("\n--- Текст поста (extracted) ---\n")
				print(jtext)
				if jimgs:
					saved = download_images(jimgs, out_dir)
					if saved:
						for s in saved:
							print(s)
				if jvids:
					savedv = download_videos(jvids, out_dir)
					if savedv:
						for s in savedv:
							print(s)
				return
		print("Не удалось извлечь текст поста. Возможно, пост приватный или структура страницы отличается.")
	else:
		out_dir = args.out_dir
		token = args.token or os.environ.get('VK_TOKEN')
		interactive_loop(out_dir, token)


if __name__ == "__main__":
	main()

