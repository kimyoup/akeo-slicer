#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, itertools, subprocess, platform, threading, queue, time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
from typing import List, Dict, Optional, Tuple, Union
from PIL import Image, ImageTk, ImageDraw
from dataclasses import dataclass
from datetime import datetime
import json

# 드래그 앤 드롭 기능 제거 (복잡하고 불필요)

try:
    from psd_tools import PSDImage
except ImportError:
    PSDImage = None

# ===== 상수 정의 =====
SUPPORTED = ('.png', '.jpg', '.jpeg', '.webp', '.psd', '.psb')
BASE_OUT = 'slices'
LOGO = 'crocodile.png'
BASE_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_FILE = BASE_DIR / 'webtoon_slicer_config.json'

# 이미지 제한 상수
PIL_MAX_PIXELS = int(2**31 - 1)
MAX_WIDTH = 10000
MAX_HEIGHT = 50000

# 업데이트 관련 상수
CURRENT_VERSION = "1.0.2"
# 구글 드라이브 설정 (실제 파일 ID로 교체하세요)
UPDATE_CHECK_URL = "https://drive.google.com/uc?id=YOUR_VERSION_FILE_ID&export=download"
DOWNLOAD_URL = "https://drive.google.com/uc?id=YOUR_EXE_FILE_ID&export=download"
GITHUB_API_URL = "https://api.github.com/repos/YOUR_GITHUB_USERNAME/akeo-slicer/releases/latest"

# UI 컬러 테마
COLORS = {
    'primary': '#4A90E2',
    'secondary': '#7B68EE',
    'accent': '#50C878',
    'warning': '#FF9500',
    'error': '#FF6B6B',
    'bg_main': '#FAFBFC',
    'bg_section': '#FFFFFF',
    'bg_hover': '#F0F4F8',
    'text_dark': '#2C3E50',
    'text_medium': '#5A6C7D',
    'text_light': '#8492A6',
    'border': '#E1E8ED',
    'success': '#4CAF50',
    'progress': '#2196F3'
}

# ===== 데이터 클래스 =====
@dataclass
class ImageInfo:
    path: Path
    width: int
    height: int
    size_bytes: int
    format: str
    
@dataclass
class MergeTask:
    files: List[Path]
    output_path: Path
    quality: str
    platform: str
    save_as_png: bool

# ===== 설정 관리 =====
class ConfigManager:
    @staticmethod
    def load():
        """설정 파일 로드"""
        default_config = {
            'quality': '무손실',
            'save_as_png': False,
            'last_input_dir': '',
            'last_output_dir': '',
            'window_geometry': '',
            'zoom_level': 50
        }
        
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    
                # 설정 검증 및 기본값 적용
                validated_config = default_config.copy()
                if isinstance(loaded_config, dict):
                    for key, value in loaded_config.items():
                        if key in default_config:
                            # 타입 검증
                            if key in ['save_as_png'] and isinstance(value, bool):
                                validated_config[key] = value
                            elif key in ['quality'] and isinstance(value, str) and value in ['무손실', 'High', 'Medium', 'Low']:
                                validated_config[key] = value
                            elif key in ['zoom_level'] and isinstance(value, (int, float)) and 5 <= value <= 200:
                                validated_config[key] = int(value)
                            elif key in ['last_input_dir', 'last_output_dir', 'window_geometry'] and isinstance(value, str):
                                validated_config[key] = value
                                
                return validated_config
                
        except Exception as e:
            print(f"설정 파일 로드 실패: {e}")
            
        return default_config
    
    @staticmethod
    def save(config):
        """설정 파일 저장"""
        try:
            # 백업 생성
            if CONFIG_FILE.exists():
                backup_file = CONFIG_FILE.with_suffix('.json.bak')
                CONFIG_FILE.replace(backup_file)
                
            # 임시 파일에 먼저 저장
            temp_file = CONFIG_FILE.with_suffix('.json.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                
            # 성공하면 실제 파일로 이동
            temp_file.replace(CONFIG_FILE)
            
        except Exception as e:
            print(f"설정 파일 저장 실패: {e}")
            # 백업 파일이 있으면 복원
            backup_file = CONFIG_FILE.with_suffix('.json.bak')
            if backup_file.exists():
                try:
                    backup_file.replace(CONFIG_FILE)
                except:
                    pass

# ===== 이미지 캐시 시스템 =====
class ImageCache:
    """이미지 캐시 관리 클래스"""
    
    def __init__(self, max_size_mb=500):
        self.cache = {}
        self.max_size_mb = max_size_mb
        self.current_size_mb = 0
        
    def get(self, path: Path, max_dimension=None):
        """캐시에서 이미지 가져오기"""
        cache_key = f"{path}_{max_dimension}"
        
        if cache_key in self.cache:
            return self.cache[cache_key].copy()
        
        # 캐시에 없으면 로드
        try:
            if path.suffix.lower() in ('.psd', '.psb'):
                img = load_psd_image(path)
            else:
                img = Image.open(path)
                
            # 크기 제한 적용
            if max_dimension and max(img.size) > max_dimension:
                ratio = max_dimension / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 메모리 사용량 계산
            img_size_mb = (img.width * img.height * len(img.getbands()) * 4) / (1024 * 1024)
            
            # 캐시 크기 체크
            if img_size_mb < 50:  # 50MB 이하만 캐시
                self._add_to_cache(cache_key, img.copy(), img_size_mb)
            
            return img
            
        except Exception as e:
            print(f"이미지 로드 실패 {path}: {e}")
            return None
    
    def _add_to_cache(self, key, img, size_mb):
        """캐시에 이미지 추가"""
        # 캐시 크기 초과 시 오래된 항목 제거
        while self.current_size_mb + size_mb > self.max_size_mb and self.cache:
            oldest_key = next(iter(self.cache))
            old_img = self.cache.pop(oldest_key)
            old_size = (old_img.width * old_img.height * len(old_img.getbands()) * 4) / (1024 * 1024)
            self.current_size_mb -= old_size
            old_img.close()
        
        self.cache[key] = img
        self.current_size_mb += size_mb
    
    def clear(self):
        """캐시 비우기"""
        for img in self.cache.values():
            img.close()
        self.cache.clear()
        self.current_size_mb = 0

# 전역 이미지 캐시
image_cache = ImageCache()

# ===== 유틸리티 함수 =====
def unique_dir(base: str) -> Path:
    """고유한 폴더명 생성"""
    p = Path(base)
    if not p.exists():
        return p
    for i in itertools.count(1):
        cand = Path(f"{base}_{i:03d}")
        if not cand.exists():
            return cand

def open_folder(path: Path):
    """폴더 열기"""
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("오류", f"폴더를 열 수 없습니다: {e}")

def format_file_size(size_bytes):
    """파일 크기 포맷팅"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}TB"

def format_image_dimensions(width: int, height: int) -> str:
    """이미지 크기를 읽기 쉬운 형식으로 변환"""
    if width is None or height is None:
        return "N/A"
    return f"{width:,}×{height:,}"

def get_image_info(path: Path) -> Optional[ImageInfo]:
    """이미지 정보 추출"""
    try:
        with Image.open(path) as img:
            return ImageInfo(
                path=path,
                width=img.width,
                height=img.height,
                size_bytes=path.stat().st_size,
                format=img.format
            )
    except:
        return None

def create_checkerboard(width, height, size=20):
    """체크무늬 배경 생성"""
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)
    
    for y in range(0, height, size):
        for x in range(0, width, size):
            if (x // size + y // size) % 2:
                draw.rectangle([x, y, x + size, y + size], fill='#E0E0E0')
    return img

def hex_to_rgb(hex_color):
    """헥스 컬러를 RGB로 변환"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

# ===== 이미지 처리 함수 =====
def save_image_with_quality(img: Image.Image, dst: Path, quality: str, 
                          save_as_png: bool = False, platform: str = None, dpi: tuple = None):
    """품질 설정에 따라 이미지 저장"""
    try:
        img_copy = img.copy()
        
        # 플랫폼별 설정 적용
        if platform and platform in PLATFORM_SPECS:
            spec = PLATFORM_SPECS[platform]
            
            # 크기 조정
            if img_copy.width > spec['max_width']:
                ratio = spec['max_width'] / img_copy.width
                new_height = int(img_copy.height * ratio)
                img_copy = img_copy.resize((spec['max_width'], new_height), Image.Resampling.LANCZOS)
            
            # 포맷 설정
            if spec['format'] == 'jpg':
                save_as_png = False
                quality = spec.get('quality', 90)
        
        # PNG로 저장
        if save_as_png:
            dst = dst.with_suffix('.png')
            if img_copy.mode != 'RGBA':
                img_copy = img_copy.convert('RGBA')
            save_kwargs = {'format': 'PNG', 'optimize': True}
            if dpi:
                save_kwargs['dpi'] = dpi
            img_copy.save(dst, **save_kwargs)
            return
            
        # JPG로 저장
        if img_copy.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img_copy.size, (255, 255, 255))
            if img_copy.mode == 'RGBA':
                background.paste(img_copy, mask=img_copy.split()[-1])
            else:
                background.paste(img_copy, mask=img_copy.split()[1])
            img_copy = background
        elif img_copy.mode != 'RGB':
            img_copy = img_copy.convert('RGB')
        
        dst = dst.with_suffix('.jpg')
        
        # 품질 설정
        quality_map = {
            '무손실': {'quality': 100, 'subsampling': 0},
            'High': {'quality': 95, 'subsampling': 0},
            'Medium': {'quality': 85},
            'Low': {'quality': 70}
        }
        
        if isinstance(quality, int):
            opts = {'quality': quality}
        else:
            opts = quality_map.get(quality, quality_map['Medium'])
        
        save_kwargs = {'format': 'JPEG', 'optimize': True, **opts}
        if dpi:
            save_kwargs['dpi'] = dpi
        
        img_copy.save(dst, **save_kwargs)
            
    except Exception as e:
        raise Exception(f"이미지 저장 실패: {str(e)}")
    finally:
        if 'img_copy' in locals():
            img_copy.close()
        if 'background' in locals():
            background.close()

def split_image_at_points_custom(src: Path, points: List[int], out: Path, 
                               quality: str, version: int, save_as_png: bool = False,
                               platform: str = None, progress_callback=None,
                               custom_filename: str = "", digits: int = 3):
    """사용자 정의 파일명으로 이미지 분할"""
    try:
        # 입력 파일 검증
        if not src.exists():
            raise FileNotFoundError(f"입력 파일이 존재하지 않습니다: {src}")
        if not src.is_file():
            raise ValueError(f"입력 경로가 파일이 아닙니다: {src}")
        if src.stat().st_size == 0:
            raise ValueError("빈 파일입니다")
            
        # 출력 폴더 생성 및 검증
        try:
            out.mkdir(parents=True, exist_ok=True)
            # 쓰기 권한 테스트
            test_file = out / '.write_test'
            test_file.write_text('test')
            test_file.unlink()
        except PermissionError:
            raise PermissionError(f"출력 폴더에 쓰기 권한이 없습니다: {out}")
        except Exception as e:
            raise Exception(f"출력 폴더 생성 실패: {e}")
        
        # PSD/PSB 지원
        if src.suffix.lower() in ('.psd', '.psb'):
            if not PSDImage:
                raise Exception("PSD 지원 라이브러리가 설치되지 않았습니다")
            img = load_psd_image(src)
            if img is None:
                raise Exception("PSD 파일을 열 수 없습니다")
        else:
            img = Image.open(src)
            
        w, h = img.size
        
        # 분할점 검증
        points = sorted(list(set(points)))  # 중복 제거 및 정렬
        if any(p <= 0 or p >= h for p in points):
            raise ValueError("분할점이 이미지 범위를 벗어났습니다")
            
        seq = [0] + points + [h]
        
        # 파일명 결정
        if custom_filename.strip():
            # 사용자 정의 파일명 정리
            base_name = custom_filename.strip()
            forbidden_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
            for char in forbidden_chars:
                base_name = base_name.replace(char, '_')
            base_name = base_name.replace(' ', '_').strip(' ._')
            if not base_name:
                base_name = src.stem
        else:
            # 원본 파일명 사용
            base_name = src.stem
        
        ext = src.suffix
        total_slices = len(seq) - 1
        
        for i in range(total_slices):
            if progress_callback:
                progress_callback(i / total_slices * 100)
                
            try:
                crop = img.crop((0, seq[i], w, seq[i + 1]))
                
                # 파일명 생성 (사용자 정의 자릿수 적용)
                if version == 0:
                    name = f"{base_name}_{i:0{digits}d}{ext}"
                else:
                    name = f"{base_name}_v{version:03d}_{i:0{digits}d}{ext}"
                    
                save_image_with_quality(crop, out / name, quality, save_as_png, platform)
                crop.close()
            except Exception as e:
                raise Exception(f"분할 {i+1}/{total_slices} 처리 중 오류: {e}")
            
        img.close()
        
        if progress_callback:
            progress_callback(100)
            
    except Exception as e:
        messagebox.showerror("분할 실패", f"이미지 분할 중 오류:\n{e}")

def split_image_at_points(src: Path, points: List[int], out: Path, 
                         quality: str, version: int, save_as_png: bool = False,
                         platform: str = None, progress_callback=None):
    """지정된 위치에서 이미지 분할"""
    try:
        # 입력 파일 검증
        if not src.exists():
            raise FileNotFoundError(f"입력 파일이 존재하지 않습니다: {src}")
        if not src.is_file():
            raise ValueError(f"입력 경로가 파일이 아닙니다: {src}")
        if src.stat().st_size == 0:
            raise ValueError("빈 파일입니다")
            
        # 출력 폴더 생성 및 검증
        try:
            out.mkdir(parents=True, exist_ok=True)
            # 쓰기 권한 테스트
            test_file = out / '.write_test'
            test_file.write_text('test')
            test_file.unlink()
        except PermissionError:
            raise PermissionError(f"출력 폴더에 쓰기 권한이 없습니다: {out}")
        except Exception as e:
            raise Exception(f"출력 폴더 생성 실패: {e}")
        
        # PSD/PSB 지원
        if src.suffix.lower() in ('.psd', '.psb'):
            if not PSDImage:
                raise Exception("PSD 지원 라이브러리가 설치되지 않았습니다")
            img = load_psd_image(src)
            if img is None:
                raise Exception("PSD 파일을 열 수 없습니다")
        else:
            img = Image.open(src)
            
        w, h = img.size
        
        # 분할점 검증
        points = sorted(list(set(points)))  # 중복 제거 및 정렬
        if any(p <= 0 or p >= h for p in points):
            raise ValueError("분할점이 이미지 범위를 벗어났습니다")
            
        seq = [0] + points + [h]
        base, ext = src.stem, src.suffix
        
        total_slices = len(seq) - 1
        
        for i in range(total_slices):
            if progress_callback:
                progress_callback(i / total_slices * 100)
                
            try:
                crop = img.crop((0, seq[i], w, seq[i + 1]))
                name = f"{base}_{i:03d}{ext}" if version == 0 else f"{base}_v{version:03d}_{i:03d}{ext}"
                save_image_with_quality(crop, out / name, quality, save_as_png, platform)
                crop.close()
            except Exception as e:
                raise Exception(f"분할 {i+1}/{total_slices} 처리 중 오류: {e}")
            
        img.close()
        
        if progress_callback:
            progress_callback(100)
            
    except Exception as e:
        messagebox.showerror("분할 실패", f"이미지 분할 중 오류:\n{e}")

def split_image_by_interval(src: Path, interval: int, out: Path, 
                           quality: str, version: int, save_as_png: bool = False,
                           platform: str = None, progress_callback=None):
    """일정 간격으로 이미지 분할"""
    try:
        # 간격 검증
        if interval <= 0:
            raise ValueError("간격은 0보다 커야 합니다")
            
        # 출력 폴더 생성
        out.mkdir(parents=True, exist_ok=True)
        
        # PSD/PSB 지원
        if src.suffix.lower() in ('.psd', '.psb'):
            if not PSDImage:
                raise Exception("PSD 지원 라이브러리가 설치되지 않았습니다")
            img = load_psd_image(src)
            if img is None:
                raise Exception("PSD 파일을 열 수 없습니다")
        else:
            img = Image.open(src)
            
        w, h = img.size
        
        # 간격이 이미지 높이보다 크면 오류
        if interval >= h:
            raise ValueError("간격이 이미지 높이보다 큽니다")
            
        points = list(range(interval, h, interval))
        img.close()
        
        split_image_at_points(src, points, out, quality, version, save_as_png, platform, progress_callback)
            
    except Exception as e:
        messagebox.showerror("분할 실패", f"이미지 분할 중 오류:\n{e}")

def merge_images_advanced(task: MergeTask, progress_callback=None, cancel_event=None):
    """고급 이미지 합치기 (진행률, 취소 지원) - 메모리 최적화"""
    if not task.files:
        return
        
    # 이미지 정보 수집
    images_info = []
    total_height = 0
    max_width = 0
    
    for i, fp in enumerate(task.files):
        if cancel_event and cancel_event.is_set():
            return
            
        info = get_image_info(fp)
        if not info:
            raise Exception(f"이미지 정보를 읽을 수 없습니다: {fp}")
            
        images_info.append(info)
        total_height += info.height
        max_width = max(max_width, info.width)
        
        if progress_callback:
            progress_callback(i / len(task.files) * 20)  # 0-20%
    
    # 크기 제한 확인
    total_pixels = max_width * total_height
    if total_pixels > PIL_MAX_PIXELS:
        raise Exception(f"이미지 크기 초과: {total_pixels:,} 픽셀 (최대 {PIL_MAX_PIXELS:,})")
    
    # 메모리 사용량 예상 (보수적 계산)
    estimated_memory_mb = (total_pixels * 4) / (1024 * 1024)  # RGBA 기준
    
    # 대용량 이미지는 스트리밍 처리
    use_streaming = estimated_memory_mb > 1000  # 1GB 이상
    
    if use_streaming:
        return _merge_images_streaming(task, images_info, max_width, total_height, 
                                     progress_callback, cancel_event)
    
    # 플랫폼별 크기 조정
    if task.platform and task.platform in PLATFORM_SPECS:
        spec = PLATFORM_SPECS[task.platform]
        if max_width > spec['max_width']:
            # 비율 유지하며 크기 조정
            scale = spec['max_width'] / max_width
            max_width = spec['max_width']
            total_height = int(total_height * scale)
    
    # 합성 이미지 생성
    mode = 'RGBA' if task.save_as_png else 'RGB'
    bg_color = (0, 0, 0, 0) if task.save_as_png else (255, 255, 255)
    
    merged = None
    try:
        merged = Image.new(mode, (max_width, total_height), bg_color)
    except MemoryError:
        raise Exception(f"메모리 부족: 예상 사용량 {estimated_memory_mb:.1f}MB")
    except Exception as e:
        raise Exception(f"이미지 생성 실패: {str(e)}")
    
    # 이미지 합치기 (메모리 효율적)
    y_offset = 0
    for i, (fp, info) in enumerate(zip(task.files, images_info)):
        if cancel_event and cancel_event.is_set():
            if merged:
                merged.close()
            return
            
        img = None
        try:
            # 캐시 사용하지 않고 직접 로드 (메모리 절약)
            if fp.suffix.lower() in ('.psd', '.psb'):
                img = load_psd_image(fp)
            else:
                img = Image.open(fp)
                
            if img is None:
                continue
                
            # 플랫폼별 크기 조정
            if task.platform and task.platform in PLATFORM_SPECS:
                spec = PLATFORM_SPECS[task.platform]
                if img.width > spec['max_width']:
                    scale = spec['max_width'] / img.width
                    new_size = (spec['max_width'], int(img.height * scale))
                    resized = img.resize(new_size, Image.Resampling.LANCZOS)
                    img.close()
                    img = resized
            
            # 모드 변환
            if img.mode != mode:
                if mode == 'RGBA':
                    converted = img.convert('RGBA')
                else:
                    if img.mode == 'RGBA':
                        bg = Image.new('RGB', img.size, (255, 255, 255))
                        bg.paste(img, mask=img.split()[-1])
                        converted = bg
                    elif img.mode != 'RGB':
                        converted = img.convert('RGB')
                    else:
                        converted = img
                
                if converted != img:
                    img.close()
                    img = converted
            
            # 중앙 정렬
            x_offset = (max_width - img.width) // 2
            merged.paste(img, (x_offset, y_offset))
            y_offset += img.height
            
        except Exception as e:
            if merged:
                merged.close()
            raise Exception(f"이미지 처리 실패 ({fp.name}): {str(e)}")
        finally:
            if img:
                img.close()
        
        if progress_callback:
            progress_callback(20 + (i + 1) / len(task.files) * 70)  # 20-90%
    
    # 이미지 저장
    try:
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        save_image_with_quality(merged, task.output_path, task.quality, 
                              task.save_as_png, task.platform)
        if progress_callback:
            progress_callback(100)  # 100%
    finally:
        if merged:
            merged.close()

def _merge_images_streaming(task, images_info, max_width, total_height, 
                          progress_callback=None, cancel_event=None):
    """대용량 이미지 스트리밍 합치기"""
    # 임시 파일 사용하여 메모리 절약
    import tempfile
    
    mode = 'RGBA' if task.save_as_png else 'RGB'
    
    # 청크 단위로 처리 (세로 1000px씩)
    chunk_height = 1000
    temp_files = []
    
    try:
        y_offset = 0
        chunk_index = 0
        
        for i, (fp, info) in enumerate(zip(task.files, images_info)):
            if cancel_event and cancel_event.is_set():
                return
                
            with Image.open(fp) as img:
                # 이미지를 청크로 분할하여 처리
                img_height = img.height
                
                for y in range(0, img_height, chunk_height):
                    chunk_bottom = min(y + chunk_height, img_height)
                    chunk = img.crop((0, y, img.width, chunk_bottom))
                    
                    # 임시 파일로 저장
                    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                    chunk.save(temp_file.name, 'PNG')
                    temp_files.append((temp_file.name, chunk.width, chunk.height, y_offset + y))
                    chunk.close()
                    temp_file.close()
            
            y_offset += img_height
            
            if progress_callback:
                progress_callback(20 + (i + 1) / len(task.files) * 60)  # 20-80%
        
        # 최종 합성
        final_img = Image.new(mode, (max_width, total_height), 
                             (0, 0, 0, 0) if mode == 'RGBA' else (255, 255, 255))
        
        for temp_path, width, height, y_pos in temp_files:
            if cancel_event and cancel_event.is_set():
                break
                
            with Image.open(temp_path) as chunk:
                x_offset = (max_width - width) // 2
                final_img.paste(chunk, (x_offset, y_pos))
        
        # 저장
        task.output_path.parent.mkdir(parents=True, exist_ok=True)
        save_image_with_quality(final_img, task.output_path, task.quality, 
                              task.save_as_png, task.platform)
        final_img.close()
        
        if progress_callback:
            progress_callback(100)
            
    finally:
        # 임시 파일 정리
        for temp_path, _, _, _ in temp_files:
            try:
                Path(temp_path).unlink()
            except:
                pass

def load_psd_image(path: Path, memory_limit: int = 2048) -> Optional[Image.Image]:
    """PSD/PSB 파일 로드"""
    try:
        # 파일 크기 사전 체크
        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > memory_limit:
            raise Exception(f"파일이 너무 큽니다 ({file_size_mb:.1f}MB > {memory_limit}MB)")
            
        psd = PSDImage.open(path)
        
        try:
            img = psd.compose()
        except AttributeError:
            try:
                img = psd.as_PIL()
            except AttributeError:
                img = psd.composite()
                
        if img is None:
            raise Exception("이미지를 추출할 수 없습니다")
        
        if not isinstance(img, Image.Image):
            img = Image.fromarray(img)
        
        # 메모리 체크 - 더 정확한 계산
        try:
            # 이미지 크기가 PIL 한계를 넘는지 확인
            total_pixels = img.width * img.height
            if total_pixels > PIL_MAX_PIXELS:
                raise Exception(f"이미지 픽셀 수 초과 ({total_pixels:,} > {PIL_MAX_PIXELS:,})")
                
            # 예상 메모리 사용량 계산 (더 보수적으로)
            estimated_mb = (img.width * img.height * len(img.getbands()) * 4) / (1024 * 1024)
            if estimated_mb > memory_limit:
                raise Exception(f"예상 메모리 사용량 초과 ({estimated_mb:.1f}MB > {memory_limit}MB)")
        except Exception as e:
            img.close()
            raise e
            
        return img
        
    except Exception as e:
        raise Exception(f"PSD 파일 로드 실패: {str(e)}")
    finally:
        # PSD 객체 정리
        if 'psd' in locals():
            try:
                psd.close()
            except:
                pass

# ===== UI 컴포넌트 =====
class ProgressDialog(tk.Toplevel):
    """진행률 표시 다이얼로그"""
    def __init__(self, parent, title="처리 중...", message="잠시만 기다려주세요"):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x150")
        self.resizable(False, False)
        self.configure(bg=COLORS['bg_main'])
        
        # 아이콘 설정
        try:
            icon_path = BASE_DIR / 'icon.ico'
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        except:
            pass
        
        # 모달 설정
        self.transient(parent)
        self.grab_set()
        
        # 메시지
        self.message_label = tk.Label(self, text=message, font=('맑은 고딕', 10),
                                    fg=COLORS['text_dark'], bg=COLORS['bg_main'])
        self.message_label.pack(pady=(20, 10))
        
        # 진행률 바
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self, variable=self.progress_var,
                                          length=350, mode='determinate')
        self.progress_bar.pack(pady=10)
        
        # 퍼센트 표시
        self.percent_label = tk.Label(self, text="0%", font=('맑은 고딕', 9),
                                    fg=COLORS['text_medium'], bg=COLORS['bg_main'])
        self.percent_label.pack()
        
        # 취소 버튼
        self.cancel_button = tk.Button(self, text="취소", command=self.cancel,
                                     font=('맑은 고딕', 9), bg=COLORS['warning'],
                                     fg='white', relief='flat', padx=20, pady=5)
        self.cancel_button.pack(pady=(10, 0))
        
        # 호버 효과
        self.cancel_button.bind('<Enter>', lambda e: self.cancel_button.configure(bg='#FF8C00'))
        self.cancel_button.bind('<Leave>', lambda e: self.cancel_button.configure(bg=COLORS['warning']))
        
        self.cancel_event = threading.Event()
        self.center_window()
        
    def center_window(self):
        """창을 화면 중앙에 배치"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        
    def update_progress(self, value):
        """진행률 업데이트"""
        self.progress_var.set(value)
        self.percent_label.config(text=f"{int(value)}%")
        self.update()
        
    def update_message(self, message):
        """메시지 업데이트"""
        self.message_label.config(text=message)
        self.update()
        
    def cancel(self):
        """작업 취소"""
        self.cancel_event.set()
        self.cancel_button.config(state='disabled', text="취소 중...")

class MergePreviewDialog(tk.Toplevel):
    """이미지 합치기 미리보기 다이얼로그"""
    def __init__(self, parent, files: List[Path]):
        super().__init__(parent)
        self.parent = parent
        self.files = list(files)
        self.result = None
        self.zoom_level = 10  # 초기 줌 레벨 10%
        
        self.title("이미지 합치기 미리보기")
        self.geometry("1000x950")  # 창 크기를 더 크게 조정
        self.configure(bg=COLORS['bg_main'])
        self.minsize(900, 850)  # 최소 크기도 증가
        
        # 아이콘 설정
        try:
            icon_path = BASE_DIR / 'icon.ico'
            if icon_path.exists():
                self.iconbitmap(str(icon_path))
        except:
            pass
        
        # 모달 설정
        self.transient(parent)
        self.grab_set()
        
        self._build_ui()
        self.center_window()
        self.load_preview()
        
    def _build_ui(self):
        # 메인 프레임
        main_frame = tk.Frame(self, bg=COLORS['bg_main'])
        main_frame.pack(fill='both', expand=True, padx=15, pady=15)
        
        # 제목
        title_label = tk.Label(main_frame, text="이미지 순서 조정",
                             font=('맑은 고딕', 14, 'bold'),
                             fg=COLORS['text_dark'], bg=COLORS['bg_main'])
        title_label.pack(pady=(0, 10))
        
        # 파일 리스트와 미리보기를 담을 프레임
        content_frame = tk.Frame(main_frame, bg=COLORS['bg_main'])
        content_frame.pack(fill='both', expand=True)
        
        # 왼쪽: 파일 리스트
        left_frame = tk.Frame(content_frame, bg=COLORS['bg_section'],
                            relief='solid', borderwidth=1)
        left_frame.pack(side='left', fill='y', padx=(0, 10))
        
        # 파일 목록 레이블
        tk.Label(left_frame, text="파일 목록", font=('맑은 고딕', 10, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).pack(pady=5)
        
        # 파일 목록 표시
        self.file_listbox = tk.Listbox(left_frame, font=('맑은 고딕', 9),
                                     selectmode='extended', relief='solid', borderwidth=1,
                                     width=30)
        self.file_listbox.pack(fill='both', expand=True, padx=5, pady=(0, 5))
        
        # 파일 목록 채우기 (제외된 파일 필터링)
        for f in self.files:
            if not hasattr(self.parent, 'merge_file_viewer') or \
               f.name not in getattr(self.parent.merge_file_viewer, 'excluded_files', set()):
                self.file_listbox.insert('end', f.name)
        
        # 파일 목록 스크롤바
        scrollbar = ttk.Scrollbar(left_frame, orient='vertical',
                                command=self.file_listbox.yview)
        scrollbar.pack(side='right', fill='y')
        self.file_listbox.configure(yscrollcommand=scrollbar.set)
        
        # 드래그 앤 드롭 바인딩
        self.file_listbox.bind('<Button-1>', self.on_listbox_click)
        self.file_listbox.bind('<B1-Motion>', self.on_listbox_drag)
        self.file_listbox.bind('<ButtonRelease-1>', self.on_listbox_release)
        
        # 오른쪽: 미리보기
        right_frame = tk.Frame(content_frame, bg=COLORS['bg_section'],
                             relief='solid', borderwidth=1)
        right_frame.pack(side='right', fill='both', expand=True)
        
        # 미리보기 컨트롤 프레임
        control_frame = tk.Frame(right_frame, bg=COLORS['bg_section'])
        control_frame.pack(fill='x', pady=(0, 5))

        # 줌 컨트롤
        zoom_frame = tk.Frame(control_frame, bg=COLORS['bg_section'])
        zoom_frame.pack(side='left')

        tk.Label(zoom_frame, text="배율:", bg=COLORS['bg_section'],
                font=('맑은 고딕', 9)).pack(side='left', padx=(5, 0))

        self.zoom_var = tk.StringVar(value="10%")  # 초기값 10%로 변경
        zoom_combo = ttk.Combobox(zoom_frame, textvariable=self.zoom_var,
                                values=['2%', '3%', '8%', '10%', '20%', '50%', '100%', '200%'],
                                width=6, state='readonly', font=('맑은 고딕', 9))
        zoom_combo.pack(side='left', padx=5)
        zoom_combo.bind('<<ComboboxSelected>>', lambda e: self._on_zoom_changed())

        # 줌 버튼들
        tk.Button(zoom_frame, text="🔍-", command=lambda: self.zoom_delta(-5),
                font=('맑은 고딕', 9), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=8, pady=2).pack(side='left', padx=2)

        tk.Button(zoom_frame, text="🔍+", command=lambda: self.zoom_delta(5),
                font=('맑은 고딕', 9), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=8, pady=2).pack(side='left', padx=2)

        tk.Button(zoom_frame, text="Fit", command=self.zoom_fit,
                font=('맑은 고딕', 9), bg=COLORS['primary'], fg='white',
                relief='flat', padx=12, pady=2).pack(side='left', padx=2)

        # 미리보기 캔버스와 스크롤바
        preview_frame = tk.Frame(right_frame)
        preview_frame.pack(fill='both', expand=True, pady=(0, 5))  # 여백 조정
        
        self.preview_canvas = tk.Canvas(preview_frame, bg='#F0F0F0',
                                      width=400, height=700)  # 높이 증가
        self.preview_canvas.pack(side='left', fill='both', expand=True)
        
        scrollbar_y = ttk.Scrollbar(preview_frame, orient='vertical', 
                                command=self.preview_canvas.yview)
        scrollbar_y.pack(side='right', fill='y')
        
        scrollbar_x = ttk.Scrollbar(right_frame, orient='horizontal', 
                                command=self.preview_canvas.xview)
        scrollbar_x.pack(side='bottom', fill='x')
        
        self.preview_canvas.configure(yscrollcommand=scrollbar_y.set,
                                    xscrollcommand=scrollbar_x.set)
        
        # 정보 표시
        info_frame = tk.Frame(main_frame, bg=COLORS['bg_main'])
        info_frame.pack(fill='x', pady=(5, 5))  # 여백 축소
        
        self.info_label = tk.Label(info_frame, text="",
                                 font=('맑은 고딕', 9),
                                 fg=COLORS['text_medium'], bg=COLORS['bg_main'])
        self.info_label.pack(side='left', padx=5)
        
        # 버튼 프레임
        button_frame = tk.Frame(main_frame, bg=COLORS['bg_main'])
        button_frame.pack(fill='x', pady=(10, 20), padx=5)  # 하단 여백 더 증가
        
        # 순서 조정 버튼들
        order_frame = tk.Frame(button_frame, bg=COLORS['bg_main'])
        order_frame.pack(side='left')
        
        move_up_btn = tk.Button(order_frame, text="↑ 위로", command=self.move_up,
                font=('맑은 고딕', 11), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=20, pady=8)
        move_up_btn.pack(side='left', padx=3)
        move_up_btn.bind('<Enter>', lambda e: move_up_btn.configure(bg='#6B58D3'))
        move_up_btn.bind('<Leave>', lambda e: move_up_btn.configure(bg=COLORS['secondary']))
                
        move_down_btn = tk.Button(order_frame, text="↓ 아래로", command=self.move_down,
                font=('맑은 고딕', 11), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=20, pady=8)
        move_down_btn.pack(side='left', padx=3)
        move_down_btn.bind('<Enter>', lambda e: move_down_btn.configure(bg='#6B58D3'))
        move_down_btn.bind('<Leave>', lambda e: move_down_btn.configure(bg=COLORS['secondary']))
                
        remove_btn = tk.Button(order_frame, text="🗑 제거", command=self.remove_file,
                font=('맑은 고딕', 11), bg=COLORS['error'], fg='white',
                relief='flat', padx=20, pady=8)
        remove_btn.pack(side='left', padx=(15, 0))
        remove_btn.bind('<Enter>', lambda e: remove_btn.configure(bg='#ff4444'))
        remove_btn.bind('<Leave>', lambda e: remove_btn.configure(bg=COLORS['error']))
        
        # 액션 버튼들
        cancel_btn = tk.Button(button_frame, text="취소", command=self.cancel,
                font=('맑은 고딕', 11), bg=COLORS['warning'], fg='white',
                relief='flat', padx=25, pady=8)
        cancel_btn.pack(side='right', padx=(15, 0))
        cancel_btn.bind('<Enter>', lambda e: cancel_btn.configure(bg='#FF8C00'))
        cancel_btn.bind('<Leave>', lambda e: cancel_btn.configure(bg=COLORS['warning']))
                
        confirm_btn = tk.Button(button_frame, text="합치기", command=self.confirm,
                font=('맑은 고딕', 11), bg=COLORS['primary'], fg='white',
                relief='flat', padx=25, pady=8)
        confirm_btn.pack(side='right')
        confirm_btn.bind('<Enter>', lambda e: confirm_btn.configure(bg='#3B7DD8'))
        confirm_btn.bind('<Leave>', lambda e: confirm_btn.configure(bg=COLORS['primary']))
        
        # 드래그 관련 변수
        self.drag_start_index = None
        
    def center_window(self):
        """창을 화면 중앙에 배치"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        
    def load_preview(self):
        """미리보기 로드"""
        if not self.files:
            return
            
        # 제외되지 않은 파일만 필터링
        active_files = []
        if hasattr(self.parent, 'merge_file_viewer'):
            excluded_files = getattr(self.parent.merge_file_viewer, 'excluded_files', set())
            active_files = [f for f in self.files if f.name not in excluded_files]
        else:
            active_files = self.files
            
        if not active_files:
            self.info_label.config(text="처리할 파일이 없습니다.")
            return
            
        # 전체 크기 계산
        total_height = 0
        max_width = 0
        
        for f in active_files:  # 활성화된 파일만 미리보기
            info = get_image_info(f)
            if info:
                total_height += info.height
                max_width = max(max_width, info.width)
        
        # 캔버스 크기에 맞게 스케일 계산
        canvas_width = 400
        canvas_height = 800
        
        # 현재 줌 레벨 적용
        scale = self.zoom_level / 100.0
        
        # 미리보기 이미지 생성
        preview_width = int(max_width * scale)
        preview_height = int(total_height * scale)
        
        preview = Image.new('RGB', (preview_width, preview_height), 'white')
        y_offset = 0
        
        for i, f in enumerate(active_files):
            try:
                                # 캐시된 이미지 사용 (미리보기용 최대 크기 제한)
                img = image_cache.get(f, max_dimension=2000)
                if img is None:
                    continue
                    
                # 스케일 적용
                img_width = int(img.width * scale)
                img_height = int(img.height * scale)
                img_resized = img.resize((img_width, img_height), Image.Resampling.LANCZOS)
                
                # 중앙 정렬
                x_offset = (preview_width - img_width) // 2
                preview.paste(img_resized, (x_offset, y_offset))
                y_offset += img_height
                
                # 구분선 그리기
                if i < len(active_files) - 1:
                    draw = ImageDraw.Draw(preview)
                    draw.line([(0, y_offset), (preview_width, y_offset)], 
                            fill='red', width=2)
                
                img.close()  # 메모리 해제
                        
            except Exception:
                pass
        
        # 캔버스에 표시
        self.photo = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        
        # 스크롤 영역 설정
        self.preview_canvas.configure(scrollregion=(0, 0, preview_width, preview_height))
        
        # 이미지 중앙 정렬
        x = max(0, (self.preview_canvas.winfo_width() - preview_width) // 2)
        y = max(0, (self.preview_canvas.winfo_height() - preview_height) // 2)
        self.preview_canvas.create_image(x, y, anchor='nw', image=self.photo)
        
        # 정보 업데이트
        total_size = sum(f.stat().st_size for f in active_files)
        self.info_label.config(
            text=f"총 {len(active_files)}개 파일 | "
                 f"크기: {format_file_size(total_size)} | "
                 f"예상 크기: {format_image_dimensions(max_width, total_height)} | "
                 f"미리보기: {self.zoom_level}% 배율"
        )
    
    def on_listbox_click(self, event):
        """리스트박스 클릭"""
        self.drag_start_index = self.file_listbox.nearest(event.y)
        
    def on_listbox_drag(self, event):
        """리스트박스 드래그"""
        if self.drag_start_index is None:
            return
            
    def on_listbox_release(self, event):
        """리스트박스 드롭"""
        if self.drag_start_index is None:
            return
            
        end_index = self.file_listbox.nearest(event.y)
        
        if self.drag_start_index != end_index:
            # 파일 순서 변경
            item = self.files.pop(self.drag_start_index)
            self.files.insert(end_index, item)
            
            # 리스트박스 업데이트
            self.file_listbox.delete(0, 'end')
            for i, f in enumerate(self.files):
                self.file_listbox.insert('end', f"{i+1}. {f.name}")
                
            # 선택 유지
            self.file_listbox.selection_set(end_index)
            
            # 미리보기 업데이트
            self.load_preview()
            
        self.drag_start_index = None
        
    def on_selection_change(self, event):
        """선택 변경"""
        pass
        
    def move_up(self):
        """선택한 파일을 위로 이동"""
        selection = self.file_listbox.curselection()
        if not selection or selection[0] == 0:
            return
            
        index = selection[0]
        self.files[index], self.files[index-1] = self.files[index-1], self.files[index]
        
        # 리스트박스 업데이트
        self.file_listbox.delete(0, 'end')
        for i, f in enumerate(self.files):
            self.file_listbox.insert('end', f"{i+1}. {f.name}")
            
        self.file_listbox.selection_set(index-1)
        self.load_preview()
        
    def move_down(self):
        """선택한 파일을 아래로 이동"""
        selection = self.file_listbox.curselection()
        if not selection or selection[0] >= len(self.files) - 1:
            return
            
        index = selection[0]
        self.files[index], self.files[index+1] = self.files[index+1], self.files[index]
        
        # 리스트박스 업데이트
        self.file_listbox.delete(0, 'end')
        for i, f in enumerate(self.files):
            self.file_listbox.insert('end', f"{i+1}. {f.name}")
            
        self.file_listbox.selection_set(index+1)
        self.load_preview()
        
    def remove_file(self):
        """선택한 파일 제거"""
        selection = self.file_listbox.curselection()
        if not selection:
            return
            
        index = selection[0]
        del self.files[index]
        
        # 리스트박스 업데이트
        self.file_listbox.delete(0, 'end')
        for i, f in enumerate(self.files):
            self.file_listbox.insert('end', f"{i+1}. {f.name}")
            
        # 선택 조정
        if self.files:
            new_index = min(index, len(self.files) - 1)
            self.file_listbox.selection_set(new_index)
            
        self.load_preview()
        
    def confirm(self):
        """확인"""
        if not self.files:
            messagebox.showwarning("경고", "파일이 없습니다.")
            return
            
        self.result = self.files
        self.destroy()
        
    def cancel(self):
        """취소"""
        self.result = None
        self.destroy()

    def zoom_delta(self, delta):
        """줌 레벨 변경"""
        new_zoom = max(2, min(200, self.zoom_level + delta))
        if new_zoom != self.zoom_level:
            self.zoom_level = new_zoom
            self.zoom_var.set(f"{self.zoom_level}%")
            self.load_preview()
    
    def zoom_fit(self):
        """이미지를 캔버스에 맞게 자동 조절"""
        if not self.files:
            return
            
        # 전체 크기 계산
        total_height = 0
        max_width = 0
        for f in self.files:
            info = get_image_info(f)
            if info:
                total_height += info.height
                max_width = max(max_width, info.width)
        
        if max_width == 0 or total_height == 0:
            return
            
        # 캔버스 크기
        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()
        
        # 가로, 세로 비율 중 더 작은 것 선택
        width_ratio = (canvas_width / max_width) * 100
        height_ratio = (canvas_height / total_height) * 100
        fit_zoom = min(width_ratio, height_ratio) * 0.9  # 90%만 사용
        
        # 25%~400% 범위로 제한
        self.zoom_level = max(25, min(400, int(fit_zoom)))
        self.zoom_var.set(f"{self.zoom_level}%")
        self.update_preview()
    
    def update_preview(self):
        """미리보기 업데이트"""
        if not self.files:
            return
            
        # 전체 크기 계산
        total_height = 0
        max_width = 0
        for f in self.files:
            info = get_image_info(f)
            if info:
                total_height += info.height
                max_width = max(max_width, info.width)
        
        if max_width == 0 or total_height == 0:
            return
            
        # 줌 스케일 계산
        scale = self.zoom_level / 100.0
        
        # 미리보기 이미지 생성
        preview_width = int(max_width * scale)
        preview_height = int(total_height * scale)
        
        preview = Image.new('RGB', (preview_width, preview_height), 'white')
        y_offset = 0
        
        for i, f in enumerate(self.files):
            try:
                with Image.open(f) as img:
                    # 스케일 적용
                    img_width = int(img.width * scale)
                    img_height = int(img.height * scale)
                    img_resized = img.resize((img_width, img_height), Image.Resampling.LANCZOS)
                    
                    # 중앙 정렬
                    x_offset = (preview_width - img_width) // 2
                    preview.paste(img_resized, (x_offset, y_offset))
                    y_offset += img_height
                    
                    # 구분선 그리기
                    if i < len(self.files) - 1:
                        draw = ImageDraw.Draw(preview)
                        draw.line([(0, y_offset), (preview_width, y_offset)], 
                                fill='red', width=2)
                        
            except Exception:
                pass
        
        # 캔버스에 표시
        self.photo = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        
        # 스크롤 영역 설정
        self.preview_canvas.configure(scrollregion=(0, 0, preview_width, preview_height))
        
        # 이미지 중앙 정렬
        x = max(0, (self.preview_canvas.winfo_width() - preview_width) // 2)
        y = max(0, (self.preview_canvas.winfo_height() - preview_height) // 2)
        self.preview_canvas.create_image(x, y, anchor='nw', image=self.photo)
        
        # 정보 업데이트
        total_size = sum(f.stat().st_size for f in self.files)
        self.info_label.config(
            text=f"총 {len(self.files)}개 파일 | "
                 f"크기: {format_file_size(total_size)} | "
                 f"예상 크기: {format_image_dimensions(max_width, total_height)} | "
                 f"미리보기: {self.zoom_level}% 배율"
        )

    def _on_zoom_changed(self):
        """배율 변경 시 호출되는 메서드"""
        try:
            new_zoom = int(self.zoom_var.get().rstrip('%'))
            self.zoom_level = new_zoom
            self.load_preview()
        except ValueError:
            pass

class ToolTip:
    """
    버튼에 대한 툴팁을 제공하는 클래스
    """
    def __init__(self, widget, text, hover_color=None, normal_color=None):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.hover_timer = None
        self.hover_color = hover_color
        self.normal_color = normal_color
        
        # 기존 이벤트 바인딩을 저장
        self.original_enter = self.widget.bind('<Enter>')
        self.original_leave = self.widget.bind('<Leave>')
        
        # 이벤트 바인딩 (기존 이벤트도 호출)
        self.widget.bind('<Enter>', self.on_enter, add='+')
        self.widget.bind('<Leave>', self.on_leave, add='+')
        self.widget.bind('<Motion>', self.on_motion, add='+')
    
    def on_enter(self, event):
        """마우스가 위젯 위에 올라갔을 때"""
        if self.hover_color:
            self.widget.configure(bg=self.hover_color)
        self.schedule_tooltip()
    
    def on_leave(self, event):
        """마우스가 위젯을 벗어났을 때"""
        if self.normal_color:
            self.widget.configure(bg=self.normal_color)
        self.cancel_tooltip()
        self.hide_tooltip()
    
    def on_motion(self, event):
        """마우스가 위젯 위에서 움직일 때"""
        self.cancel_tooltip()
        self.schedule_tooltip()
    
    def schedule_tooltip(self):
        """5초 후 툴팁 표시 예약"""
        self.cancel_tooltip()
        self.hover_timer = self.widget.after(5000, self.show_tooltip)
    
    def cancel_tooltip(self):
        """툴팁 표시 취소"""
        if self.hover_timer:
            self.widget.after_cancel(self.hover_timer)
            self.hover_timer = None
    
    def show_tooltip(self):
        """툴팁 표시"""
        if self.tooltip_window:
            return
        
        try:
            x = self.widget.winfo_rootx() + 25
            y = self.widget.winfo_rooty() + 25
            
            self.tooltip_window = tk.Toplevel(self.widget)
            self.tooltip_window.wm_overrideredirect(True)
            self.tooltip_window.wm_geometry(f"+{x}+{y}")
            
            label = tk.Label(self.tooltip_window, text=self.text,
                            font=('맑은 고딕', 9), bg='#FFFFCC', fg='black',
                            relief='solid', borderwidth=1, padx=8, pady=4)
            label.pack()
            
            # 10초 후 자동 숨김
            self.widget.after(10000, self.hide_tooltip)
        except:
            # 위젯이 파괴된 경우 등의 오류 처리
            pass
    
    def hide_tooltip(self):
        """툴팁 숨김"""
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except:
                pass
            self.tooltip_window = None


class FileListViewer:
    def __init__(self, parent, title="파일 목록"):
        self.parent = parent
        self.window = None
        self.tree = None
        self.title = title
        self.excluded_files = set()
        self.on_files_updated = None
        self.custom_order = []
        self.status_label = None
        self.sort_column = "name"
        self.sort_reverse = False
        self.total_files = 0
        self.total_size = 0

    def show(self, directory: Path, file_types=SUPPORTED):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
            
        self.window = tk.Toplevel(self.parent)
        self.window.title(f"{self.title} - {directory.name}")
        self.window.geometry("500x700")
        self.window.configure(bg=COLORS['bg_main'])
        
        # 아이콘 설정
        try:
            icon_path = BASE_DIR / 'icon.ico'
            if icon_path.exists():
                self.window.iconbitmap(str(icon_path))
        except:
            pass
        
        # 메인 프레임
        main_frame = tk.Frame(self.window, bg=COLORS['bg_main'])
        main_frame.pack(fill='both', expand=True, padx=20, pady=(10, 5))
        
        # 상단 정보 프레임
        info_frame = tk.Frame(main_frame, bg=COLORS['bg_main'])
        info_frame.pack(fill='x', pady=(0, 10))
        
        # 폴더 경로
        path_frame = tk.Frame(info_frame, bg=COLORS['bg_main'])
        path_frame.pack(fill='x', pady=(0, 5))
        
        tk.Label(path_frame, text="📁", font=('맑은 고딕', 12),
                fg=COLORS['text_dark'], bg=COLORS['bg_main']).pack(side='left')
        
        tk.Label(path_frame, text=str(directory), font=('맑은 고딕', 10),
                fg=COLORS['text_medium'], bg=COLORS['bg_main']).pack(side='left', padx=(5, 0))
        
        # 통계 정보
        self.stats_frame = tk.Frame(info_frame, bg=COLORS['bg_main'])
        self.stats_frame.pack(fill='x')
        
        # 트리뷰 프레임
        tree_frame = tk.Frame(main_frame, bg=COLORS['border'], relief='solid', borderwidth=1)
        tree_frame.pack(fill='both', expand=True)
        
        # 트리뷰
        columns = ('size', 'dimensions', 'modified', 'status')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='tree headings', height=20)

        # 스타일 설정
        style = ttk.Style()
        style.configure('Treeview', font=('맑은 고딕', 9))
        style.configure('Treeview.Heading', font=('맑은 고딕', 9, 'bold'))

        # 컬럼 설정
        column_info = {
            '#0': ('파일명', 350, 'w'),
            'size': ('크기', 100, 'center'),
            'dimensions': ('해상도', 150, 'center'),
            'modified': ('수정일', 120, 'center'),
            'status': ('상태', 60, 'center')
        }
        
        for col, (text, width, anchor) in column_info.items():
            if col == '#0':
                self.tree.heading(col, text=text, anchor=anchor,
                                command=lambda: self._sort_tree('name'))
            else:
                self.tree.heading(col, text=text, anchor=anchor,
                                command=lambda c=col: self._sort_tree(c))
            self.tree.column(col, width=width, anchor=anchor)
        
        # 스크롤바 (세로만 사용)
        v_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=v_scroll.set)
        
        # 그리드 배치
        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        
        # 우클릭 메뉴
        self.context_menu = tk.Menu(self.window, tearoff=0)
        self.context_menu.add_command(label="제외하기", command=self.exclude_selected)
        self.context_menu.add_command(label="제외 취소", command=self.include_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="파일 열기", command=self.open_file)
        self.context_menu.add_command(label="폴더에서 보기", command=self.show_in_folder)
        
        # 이벤트 바인딩
        self.tree.bind('<Button-3>', self.show_context_menu)
        self.tree.bind('<Double-Button-1>', lambda e: self.open_file())
        self.tree.bind('<Button-1>', self.on_click)
        self.tree.bind('<B1-Motion>', self.on_drag)
        self.tree.bind('<ButtonRelease-1>', self.on_drop)
        
        # 마우스 휠 이벤트 바인딩
        self.tree.bind('<MouseWheel>', lambda e: on_mousewheel(e, self.tree))  # Windows
        self.tree.bind('<Button-4>', lambda e: on_mousewheel(e, self.tree))  # Linux
        self.tree.bind('<Button-5>', lambda e: on_mousewheel(e, self.tree))  # Linux
        
        # 파일 로드
        self.current_directory = directory
        self.current_file_types = file_types
        self.load_files(directory, file_types)

    def update_stats(self):
        """통계 정보 업데이트"""
        for widget in self.stats_frame.winfo_children():
            widget.destroy()
            
        stats = [
            ("📊 전체", f"{self.total_files}개"),
            ("📦 크기", format_file_size(self.total_size)),
            ("🚫 제외", f"{len(self.excluded_files)}개")
        ]
        
        for i, (icon_text, value) in enumerate(stats):
            if i > 0:
                tk.Label(self.stats_frame, text="•", font=('맑은 고딕', 9),
                        fg=COLORS['text_light'], bg=COLORS['bg_main']).pack(side='left', padx=8)
                        
            tk.Label(self.stats_frame, text=icon_text, font=('맑은 고딕', 9),
                    fg=COLORS['text_medium'], bg=COLORS['bg_main']).pack(side='left')
            tk.Label(self.stats_frame, text=value, font=('맑은 고딕', 9, 'bold'),
                    fg=COLORS['text_dark'], bg=COLORS['bg_main']).pack(side='left', padx=(3, 0))

    def load_files(self, directory: Path, file_types):
        """파일 목록 로드"""
        if not self.tree:
            return
            
        self.tree.delete(*self.tree.get_children())
        self.total_files = 0
        self.total_size = 0
            
        try:
            files = []
            for ext in file_types:
                files.extend(directory.glob(f"*{ext}"))
            
            files = list(set(files))
            
            if self.custom_order:
                new_files = [f for f in files if f.name not in self.custom_order]
                new_files.sort(key=lambda x: x.name.lower())
                
                sorted_files = []
                for name in self.custom_order:
                    matching_files = [f for f in files if f.name == name]
                    if matching_files:
                        sorted_files.extend(matching_files)
                sorted_files.extend(new_files)
                files = sorted_files
            else:
                files.sort(key=lambda x: x.name.lower())
            
            for file_path in files:
                try:
                    is_excluded = file_path.name in self.excluded_files
                    if is_excluded and not self.show_excluded_var.get():
                        continue
                        
                    # 파일 정보
                    stat = file_path.stat()
                    size = format_file_size(stat.st_size)
                    modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                    
                    # 이미지 정보
                    img_info = get_image_info(file_path)
                    dimensions = format_image_dimensions(img_info.width, img_info.height) if img_info else "N/A"
                    
                    # 아이콘 선택
                    ext = file_path.suffix.lower()
                    icon = '🖼️' if ext == '.png' else '📷' if ext in ['.jpg', '.jpeg'] else '🎨' if ext == '.webp' else '📄'
                    
                    display_name = f"{icon} {file_path.name}"
                    status = "제외" if is_excluded else ""
                    
                    item = self.tree.insert('', 'end', text=display_name,
                                          values=(size, dimensions, modified, status))
                    
                    if is_excluded:
                        self.tree.tag_configure('excluded', foreground=COLORS['text_light'])
                        self.tree.item(item, tags=('excluded',))
                    else:
                        self.total_size += stat.st_size
                    
                    self.total_files += 1
                        
                except Exception as e:
                    print(f"파일 로드 오류 ({file_path.name}): {e}")
                    continue
            
            # 통계 업데이트
            self.update_stats()
            
            # 정렬 적용
            if self.sort_column:
                self._sort_tree(self.sort_column)
                
        except Exception as e:
            messagebox.showerror("오류", f"파일 목록을 불러올 수 없습니다: {e}")

    def set_callback(self, callback):
        """콜백 함수 설정"""
        self.on_files_updated = callback
    
    def _on_close(self):
        """창 닫기 처리"""
        if self.window:
            # 콜백 함수 호출
            if self.on_files_updated:
                self.on_files_updated()
            
            # 창 닫기
            self.window.destroy()
            self.window = None
            self.tree = None
            self.status_label = None
        
    def show(self, directory: Path, file_types=SUPPORTED):
        """파일 목록 창 표시"""
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
            
        self.window = tk.Toplevel(self.parent)
        self.window.title(f"{self.title} - {directory.name}")
        self.window.geometry("1000x800")  # 창 크기 증가
        self.window.minsize(900, 700)  # 최소 크기 설정
        self.window.configure(bg=COLORS['bg_main'])
        
        # 창이 닫힐 때 이벤트 처리 (X 버튼 클릭)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        # ESC 키로도 창 닫기
        self.window.bind('<Escape>', lambda e: self._on_close())
        
        # 메인 프레임
        main_frame = tk.Frame(self.window, bg=COLORS['bg_main'])
        main_frame.pack(fill='both', expand=True, padx=10, pady=(10, 5))
        
        # 상단 정보 프레임
        info_frame = tk.Frame(main_frame, bg=COLORS['bg_main'])
        info_frame.pack(fill='x', pady=(0, 10))
        
        # 폴더 경로
        path_frame = tk.Frame(info_frame, bg=COLORS['bg_main'])
        path_frame.pack(fill='x', pady=(0, 5))
        
        tk.Label(path_frame, text="📁", font=('맑은 고딕', 12),
                fg=COLORS['text_dark'], bg=COLORS['bg_main']).pack(side='left')
        
        tk.Label(path_frame, text=str(directory), font=('맑은 고딕', 10),
                fg=COLORS['text_medium'], bg=COLORS['bg_main']).pack(side='left', padx=(5, 0))
        
        # 통계 정보
        self.stats_frame = tk.Frame(info_frame, bg=COLORS['bg_main'])
        self.stats_frame.pack(fill='x')
        
        # 트리뷰 프레임
        tree_frame = tk.Frame(main_frame, bg=COLORS['border'], relief='solid', borderwidth=1)
        tree_frame.pack(fill='both', expand=True)
        
        # 트리뷰
        columns = ('size', 'dimensions', 'modified', 'status')
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='tree headings', height=20, xscrollcommand=None)
        
        # 스타일 설정
        style = ttk.Style()
        style.configure('Treeview', font=('맑은 고딕', 9))
        style.configure('Treeview.Heading', font=('맑은 고딕', 9, 'bold'))
        
        # 컬럼 설정
        column_info = {
            '#0': ('파일명', 250, 'w'),  # 파일명 컬럼
            'size': ('크기', 80, 'center'),  # 크기 컬럼
            'dimensions': ('해상도', 120, 'center'),  # 해상도 컬럼
            'modified': ('수정일', 150, 'center'),  # 수정일 컬럼
            'status': ('상태', 60, 'center')  # 상태 컬럼
        }
        
        for col, (text, width, anchor) in column_info.items():
            if col == '#0':
                self.tree.heading(col, text=text, anchor=anchor,
                                command=lambda: self._sort_tree('name'))
            else:
                self.tree.heading(col, text=text, anchor=anchor,
                                command=lambda c=col: self._sort_tree(c))
            self.tree.column(col, width=width, anchor=anchor)
        
        # 스크롤바
        v_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        h_scroll = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        
        # 그리드 배치
        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        h_scroll.grid(row=1, column=0, sticky='ew')
        
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        
        # 우클릭 메뉴
        self.context_menu = tk.Menu(self.window, tearoff=0)
        self.context_menu.add_command(label="제외하기", command=self.exclude_selected)
        self.context_menu.add_command(label="제외 취소", command=self.include_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="파일 열기", command=self.open_file)
        self.context_menu.add_command(label="폴더에서 보기", command=self.show_in_folder)
        
        # 이벤트 바인딩
        self.tree.bind('<Button-3>', self.show_context_menu)
        self.tree.bind('<Double-Button-1>', lambda e: self.open_file())
        self.tree.bind('<Button-1>', self.on_click)
        self.tree.bind('<B1-Motion>', self.on_drag)
        self.tree.bind('<ButtonRelease-1>', self.on_drop)
        
        # 마우스 휠 이벤트 바인딩
        self.tree.bind('<MouseWheel>', lambda e: on_mousewheel(e, self.tree))  # Windows
        self.tree.bind('<Button-4>', lambda e: on_mousewheel(e, self.tree))  # Linux
        self.tree.bind('<Button-5>', lambda e: on_mousewheel(e, self.tree))  # Linux
        
        # 파일 로드
        self.current_directory = directory
        self.current_file_types = file_types
        self.load_files(directory, file_types)
        
        # 버튼 프레임
        btn_frame = tk.Frame(main_frame, bg=COLORS['bg_main'])
        btn_frame.pack(fill='x', pady=(10, 10))
        
        # 필터 옵션
        filter_frame = tk.Frame(btn_frame, bg=COLORS['bg_main'])
        filter_frame.pack(side='left')
        
        self.show_excluded_var = tk.BooleanVar(value=True)
        show_excluded_check = tk.Checkbutton(filter_frame, text="제외된 파일 표시", 
                                           variable=self.show_excluded_var,
                                           command=self.refresh,
                                           font=('맑은 고딕', 9),
                                           fg=COLORS['text_medium'], bg=COLORS['bg_main'])
        show_excluded_check.pack(side='left')
        
        # 정렬 옵션
        tk.Label(filter_frame, text="정렬:", font=('맑은 고딕', 9),
                fg=COLORS['text_medium'], bg=COLORS['bg_main']).pack(side='left', padx=(20, 5))
        
        self.sort_var = tk.StringVar(value="이름")
        sort_combo = ttk.Combobox(filter_frame, textvariable=self.sort_var,
                                values=["이름", "크기", "수정일", "사용자 정의"],
                                width=10, state='readonly')
        sort_combo.pack(side='left')
        sort_combo.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        
        # 액션 버튼들
        tk.Button(btn_frame, text="📂 폴더 열기", 
                command=lambda: open_folder(directory),
                font=('맑은 고딕', 10), bg=COLORS['primary'], fg='white',
                relief='flat', padx=15, pady=5).pack(side='right', padx=(5, 0))
        
        tk.Button(btn_frame, text="🔄 새로고침", 
                command=self.refresh,
                font=('맑은 고딕', 10), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=15, pady=5).pack(side='right', padx=(5, 0))
        
        tk.Button(btn_frame, text="전체 선택", 
                command=self.select_all,
                font=('맑은 고딕', 10), bg=COLORS['accent'], fg='white',
                relief='flat', padx=15, pady=5).pack(side='right', padx=(5, 0))
        
        # 상태바
        self.status_label = tk.Label(main_frame, text="", font=('맑은 고딕', 9),
                                   fg=COLORS['text_light'], bg=COLORS['bg_main'])
        self.status_label.pack(fill='x', pady=(5, 0))
        
        self.window.bind('<Destroy>', self.on_destroy)
        
    def refresh(self):
        """새로고침"""
        self.load_files(self.current_directory, self.current_file_types)
        
    def select_all(self):
        """전체 선택"""
        for item in self.tree.get_children():
            self.tree.selection_add(item)
            
    def open_file(self):
        """선택한 파일 열기"""
        selection = self.tree.selection()
        if not selection:
            return
            
        item = selection[0]
        file_name = self.tree.item(item)['text'].split(' ', 1)[1]
        file_path = self.current_directory / file_name
        
        try:
            if platform.system() == "Windows":
                os.startfile(file_path)
            elif platform.system() == "Darwin":
                subprocess.run(["open", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
        except Exception as e:
            messagebox.showerror("오류", f"파일을 열 수 없습니다: {e}")
            
    def show_in_folder(self):
        """폴더에서 파일 표시"""
        selection = self.tree.selection()
        if not selection:
            return
            
        item = selection[0]
        file_name = self.tree.item(item)['text'].split(' ', 1)[1]
        file_path = self.current_directory / file_name
        
        try:
            if platform.system() == "Windows":
                subprocess.run(['explorer', '/select,', str(file_path)])
            elif platform.system() == "Darwin":
                subprocess.run(["open", "-R", file_path])
            else:
                open_folder(file_path.parent)
        except Exception as e:
            messagebox.showerror("오류", f"폴더를 열 수 없습니다: {e}")
            
    def show_context_menu(self, event):
        """우클릭 메뉴 표시"""
        # 클릭된 아이템 확인
        clicked_item = self.tree.identify_row(event.y)
        
        # 현재 선택된 아이템들 확인
        selected_items = self.tree.selection()
        
        # 클릭된 위치에 아이템이 있고, 해당 아이템이 선택되지 않은 경우
        if clicked_item and clicked_item not in selected_items:
            # 기존 선택 해제하고 클릭된 아이템만 선택
            self.tree.selection_set(clicked_item)
        
        # 선택된 아이템이 있는 경우에만 메뉴 표시
        if self.tree.selection():
            self.context_menu.post(event.x_root, event.y_root)
    
    def exclude_selected(self):
        """선택한 파일들 제외"""
        for item in self.tree.selection():
            file_name = self.tree.item(item)['text'].split(' ', 1)[1]  # "🖼 파일명"에서 파일명만 추출
            self.excluded_files.add(file_name)
            self.tree.item(item, tags=('excluded',))
            self.tree.set(item, 'status', "제외")
        
        # 상태 업데이트
        if self.status_label:
            total = len(self.tree.get_children())
            excluded = len(self.excluded_files)
            self.status_label.config(text=f"총 {total}개 파일 (제외: {excluded}개)")
        
        # 콜백 호출
        if self.on_files_updated:
            self.on_files_updated()
    
    def include_selected(self):
        """선택한 파일들 제외 취소"""
        for item in self.tree.selection():
            file_name = self.tree.item(item)['text'].split(' ', 1)[1]  # "🖼 파일명"에서 파일명만 추출
            if file_name in self.excluded_files:
                self.excluded_files.remove(file_name)
                self.tree.item(item, tags=('default',))
                self.tree.set(item, 'status', "")
        
        # 상태 업데이트
        if self.status_label:
            total = len(self.tree.get_children())
            excluded = len(self.excluded_files)
            self.status_label.config(text=f"총 {total}개 파일 (제외: {excluded}개)")
        
        # 콜백 호출
        if self.on_files_updated:
            self.on_files_updated()

    def on_click(self, event):
        """클릭 이벤트"""
        self.tree.selection_set(self.tree.identify_row(event.y))
        self.drag_start_y = event.y
        self.drag_item = self.tree.identify_row(event.y)

    def on_drag(self, event):
        """드래그 이벤트"""
        if hasattr(self, 'drag_item') and self.drag_item:
            self.tree.yview_scroll(int((event.y - self.drag_start_y) / 20), 'units')
            
    def on_drop(self, event):
        """드롭 이벤트"""
        if not hasattr(self, 'drag_item') or not self.drag_item:
            return
            
        target_item = self.tree.identify_row(event.y)
        if not target_item or target_item == self.drag_item:
            return

        # 항목 정보 저장
        drag_text = self.tree.item(self.drag_item)['text']
        drag_values = self.tree.item(self.drag_item)['values']
        drag_tags = self.tree.item(self.drag_item)['tags']

        # 드롭 위치 결정
        target_bbox = self.tree.bbox(target_item)
        if target_bbox:
            target_y = target_bbox[1]
            is_above = event.y < target_y + target_bbox[3] // 2

        # 항목 이동
        self.tree.delete(self.drag_item)
        if is_above:
            new_item = self.tree.insert(parent='', index=self.tree.index(target_item),
                                      text=drag_text, values=drag_values, tags=drag_tags)
        else:
            new_item = self.tree.insert(parent='', index=self.tree.index(target_item) + 1,
                                      text=drag_text, values=drag_values, tags=drag_tags)

        self.tree.selection_set(new_item)
        self.update_custom_order()
        
        if self.on_files_updated:
            self.on_files_updated()

    def update_custom_order(self):
        """사용자 정의 순서 업데이트"""
        self.custom_order = []
        for item in self.tree.get_children():
            file_name = self.tree.item(item)['text'].split(' ', 1)[1]
            self.custom_order.append(file_name)
        
    def load_files(self, directory: Path, file_types):
        """파일 목록 로드"""
        if not self.tree:
            return
            
        self.tree.delete(*self.tree.get_children())
        self.total_files = 0
        self.total_size = 0
            
        try:
            files = []
            for ext in file_types:
                files.extend(directory.glob(f"*{ext}"))
            
            files = list(set(files))
            
            if self.custom_order:
                new_files = [f for f in files if f.name not in self.custom_order]
                new_files.sort(key=lambda x: x.name.lower())
                
                sorted_files = []
                for name in self.custom_order:
                    matching_files = [f for f in files if f.name == name]
                    if matching_files:
                        sorted_files.extend(matching_files)
                sorted_files.extend(new_files)
                files = sorted_files
            else:
                files.sort(key=lambda x: x.name.lower())
            
            for file_path in files:
                try:
                    is_excluded = file_path.name in self.excluded_files
                    if is_excluded and not self.show_excluded_var.get():
                        continue
                        
                    # 파일 정보
                    stat = file_path.stat()
                    size = format_file_size(stat.st_size)
                    modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                    
                    # 이미지 정보
                    img_info = get_image_info(file_path)
                    dimensions = format_image_dimensions(img_info.width, img_info.height) if img_info else "N/A"
                    
                    # 아이콘 선택
                    ext = file_path.suffix.lower()
                    icon = '🖼️' if ext == '.png' else '📷' if ext in ['.jpg', '.jpeg'] else '🎨' if ext == '.webp' else '📄'
                    
                    display_name = f"{icon} {file_path.name}"
                    status = "제외" if is_excluded else ""
                    
                    item = self.tree.insert('', 'end', text=display_name,
                                          values=(size, dimensions, modified, status))
                    
                    if is_excluded:
                        self.tree.tag_configure('excluded', foreground=COLORS['text_light'])
                        self.tree.item(item, tags=('excluded',))
                    else:
                        self.total_size += stat.st_size
                    
                    self.total_files += 1
                        
                except Exception as e:
                    print(f"파일 로드 오류 ({file_path.name}): {e}")
                    continue
            
                        # 통계 정보 업데이트
            if hasattr(self, 'stats_frame'):
                for widget in self.stats_frame.winfo_children():
                    widget.destroy()
                
                stats = [
                    ("📊 전체", f"{self.total_files:,}개"),
                    ("📦 크기", format_file_size(self.total_size)),
                    ("🚫 제외", f"{len(self.excluded_files):,}개")
                ]
                
                for i, (icon_text, value) in enumerate(stats):
                    if i > 0:
                        tk.Label(self.stats_frame, text="•", font=('맑은 고딕', 9),
                                fg=COLORS['text_light'], bg=COLORS['bg_main']).pack(side='left', padx=8)
                    
                    tk.Label(self.stats_frame, text=icon_text, font=('맑은 고딕', 9),
                            fg=COLORS['text_medium'], bg=COLORS['bg_main']).pack(side='left')
                    tk.Label(self.stats_frame, text=value, font=('맑은 고딕', 9, 'bold'),
                            fg=COLORS['text_dark'], bg=COLORS['bg_main']).pack(side='left', padx=(3, 0))
            
            # 정렬 적용
            if self.sort_column:
                self._sort_tree(self.sort_column)
                
        except Exception as e:
            messagebox.showerror("오류", f"파일 목록을 불러올 수 없습니다: {e}")

    def _sort_tree(self, col):
        """트리뷰 정렬"""
        if self.sort_column == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col
            self.sort_reverse = False
        
        # 현재 항목들을 모두 가져옴
        items = [(self.tree.set(item, col) if col != 'name' else self.tree.item(item)['text'],
                 item) for item in self.tree.get_children('')]
        
        # 정렬 키 함수 정의
        def sort_key(item):
            value = item[0]
            if col == 'size':
                # 크기를 바이트 단위로 변환
                units = {'B': 1, 'KB': 1024, 'MB': 1024*1024, 'GB': 1024*1024*1024}
                try:
                    num, unit = value.split()
                    return float(num) * units.get(unit.strip(), 0)
                except:
                    return 0
            elif col == 'dimensions':
                # 해상도를 픽셀 수로 변환
                try:
                    w, h = value.split('×')
                    return int(w) * int(h)
                except:
                    return 0
            elif col == 'modified':
                # 날짜를 timestamp로 변환
                try:
                    return datetime.strptime(value, '%Y-%m-%d %H:%M').timestamp()
                except:
                    return 0
            elif col == 'name':
                # 파일명에서 아이콘 제거
                return value.split(' ', 1)[1].lower()
            return value.lower()

        # 정렬 실행
        items.sort(key=sort_key, reverse=self.sort_reverse)
        
        # 트리뷰 재구성
        for idx, (_, item) in enumerate(items):
            self.tree.move(item, '', idx)
            
        # 정렬 방향 표시
        for col_name in ['#0'] + list(self.tree['columns']):
            if col_name == '#0' and self.sort_column == 'name':
                self.tree.heading(col_name, text=f"{'↓' if self.sort_reverse else '↑'} 파일명")
            elif col_name == self.sort_column:
                current_text = self.tree.heading(col_name)['text'].split()[-1]
                self.tree.heading(col_name, text=f"{'↓' if self.sort_reverse else '↑'} {current_text}")
            else:
                if col_name == '#0':
                    self.tree.heading(col_name, text="파일명")
                else:
                    self.tree.heading(col_name, text=self.tree.heading(col_name)['text'].split()[-1])

    def on_destroy(self, event=None):
        """창 닫기"""
        if event and event.widget != self.window:
            return
        self.window = None
        self.tree = None
        self.status_label = None

class PreviewWindow:
    """미리보기 창 (개선된 버전)"""
    shared_zoom_ratio = 50
    keep_ratio_fixed = False
    shared_bg_color = '#808080'
    keep_bg_fixed = False
    
    def __init__(self, parent, file_row):
        self.parent = parent
        self.file_row = file_row
        self.window = None
        self.canvas = None
        self.img_original = None
        self.img_display = None
        self.photo = None
        self.zoom_ratio = PreviewWindow.shared_zoom_ratio
        self.bg_color = PreviewWindow.shared_bg_color
        self.cut_points = []
        self.selected_point_idx = None
        self.dragging = False
        self.x_offset = 0
        self.y_offset = 0
        self.status_text = None
        self.undo_stack = []  # 실행 취소 스택
        self.redo_stack = []  # 다시 실행 스택
        
    def show(self):
        """미리보기 창 표시"""
        if not self.file_row.path or not self.file_row.path.exists():
            messagebox.showerror("오류", "이미지 파일이 선택되지 않았습니다.")
            return
            
        if self.window:
            self.window.lift()
            return
            
        self.window = tk.Toplevel(self.parent)
        self.window.title(f"미리보기 - {self.file_row.file.get()}")
        self.window.geometry("1000x800")
        self.window.configure(bg=COLORS['bg_main'])
        
        # 아이콘 설정
        try:
            icon_path = BASE_DIR / 'icon.ico'
            if icon_path.exists():
                self.window.iconbitmap(str(icon_path))
        except:
            pass
        
        # 창이 닫힐 때 이벤트 처리
        self.window.protocol("WM_DELETE_WINDOW", lambda: self.window.destroy())
        
        # 메인 프레임
        main_frame = tk.Frame(self.window, bg=COLORS['bg_main'])
        main_frame.pack(fill='both', expand=True, padx=15, pady=15)
        
        # 컨트롤 패널
        control_panel = tk.Frame(main_frame, bg=COLORS['bg_section'], relief='solid', 
                               borderwidth=1, padx=15, pady=12)
        control_panel.pack(fill='x', pady=(0, 15))
        
        # 제목
        title_label = tk.Label(control_panel, text="분할점 선택", 
                              font=('맑은 고딕', 14, 'bold'), 
                              fg=COLORS['text_dark'], bg=COLORS['bg_section'])
        title_label.pack(anchor='w', pady=(0, 10))
        
        # 도구 모음
        toolbar = tk.Frame(control_panel, bg=COLORS['bg_section'])
        toolbar.pack(fill='x', pady=(0, 10))
        
        # 줌 컨트롤
        zoom_frame = tk.Frame(toolbar, bg=COLORS['bg_section'])
        zoom_frame.pack(side='left')
        
        tk.Label(zoom_frame, text="확대/축소:", font=('맑은 고딕', 10), 
                fg=COLORS['text_medium'], bg=COLORS['bg_section']).pack(side='left')
        
        zoom_buttons = [
            ("➖", lambda: self.zoom_delta(-10)),
            ("🔍", lambda: self.zoom_fit()),
            ("➕", lambda: self.zoom_delta(10)),
            ("100%", lambda: self.set_zoom_ratio("100%"))
        ]
        
        for text, cmd in zoom_buttons:
            tk.Button(zoom_frame, text=text, command=cmd,
                    font=('맑은 고딕', 9), relief='flat',
                    padx=10, pady=3).pack(side='left', padx=2)
        
        self.ratio_var = tk.StringVar(value=f"{self.zoom_ratio}%")
        ratio_combo = ttk.Combobox(zoom_frame, textvariable=self.ratio_var, 
                                  values=['3%','5%', '10%', '25%', '50%', '75%', '100%', '150%', '200%'], 
                                  width=8, state='readonly', font=('맑은 고딕', 9))
        ratio_combo.pack(side='left', padx=(5, 15))
        ratio_combo.bind('<<ComboboxSelected>>', lambda e: self.set_zoom_ratio(self.ratio_var.get()))
        
        # 배경 설정
        bg_frame = tk.Frame(toolbar, bg=COLORS['bg_section'])
        bg_frame.pack(side='left')
        
        tk.Label(bg_frame, text="배경:", font=('맑은 고딕', 10), 
                fg=COLORS['text_medium'], bg=COLORS['bg_section']).pack(side='left')
        
        self.bg_color_btn = tk.Button(bg_frame, text="    ", width=3, 
                                     bg=self.bg_color, command=self.choose_bg_color,
                                     relief='solid', borderwidth=1)
        self.bg_color_btn.pack(side='left', padx=(5, 5))
        
        # 프리셋 버튼
        presets = [
            ('#FFFFFF', '⚪'),
            ('#000000', '⚫'),
            ('#808080', '🔘'),
            # ('checkerboard', '🏁')
        ]
        for color, icon in presets:
            tk.Button(bg_frame, text=icon, command=lambda c=color: self.set_bg_color(c),
                    font=('맑은 고딕', 12), relief='flat',
                    padx=5, pady=2).pack(side='left', padx=1)
        
        # 도구 버튼
        tools_frame = tk.Frame(toolbar, bg=COLORS['bg_section'])
        tools_frame.pack(side='left', padx=(20, 0))
        
        tool_buttons = [
            ("↩️ 실행취소", self.undo),
            ("↪️ 다시실행", self.redo),
            ("🎯 스냅", self.toggle_snap)
        ]
        
        for text, cmd in tool_buttons:
            tk.Button(tools_frame, text=text, command=cmd,
                    font=('맑은 고딕', 9), relief='flat',
                    padx=10, pady=3).pack(side='left', padx=2)
        
        # 액션 버튼
        action_frame = tk.Frame(control_panel, bg=COLORS['bg_section'])
        action_frame.pack(fill='x')
        
        # 기본 상태 정보 (왼쪽)
        self.status_label = tk.Label(action_frame, text="",
                                   font=('맑은 고딕', 9), fg=COLORS['text_medium'], 
                                   bg=COLORS['bg_section'])
        self.status_label.pack(side='left', padx=(0, 20))
        
        # 상태 메시지 (중앙)
        self.message_label = tk.Label(action_frame, text="",
                                   font=('맑은 고딕', 12, 'bold'), fg=COLORS['success'], 
                                   bg=COLORS['bg_section'])
        self.message_label.pack(side='left', expand=True)
        
        # 분할설정, 자동분할, 초기화 버튼을 오른쪽에 배치
        tk.Button(action_frame, text="초기화", command=self.clear_points,
                font=('맑은 고딕', 10), bg=COLORS['warning'], fg='white',
                relief='flat', padx=15, pady=5).pack(side='right', padx=2)
        
        tk.Button(action_frame, text="자동분할", command=self.auto_split,
                font=('맑은 고딕', 10), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=15, pady=5).pack(side='right', padx=2)
        
        tk.Button(action_frame, text="설정완료", command=self.apply_points,
                font=('맑은 고딕', 10), bg=COLORS['primary'], fg='white',
                relief='flat', padx=15, pady=5).pack(side='right', padx=2)
        
        # 캔버스 영역
        canvas_container = tk.Frame(main_frame, bg=COLORS['bg_section'])
        canvas_container.pack(fill='both', expand=True)
        
        # 눈금자
        ruler_size = 30
        
        # 상단 눈금자
        self.h_ruler = tk.Canvas(canvas_container, height=ruler_size, 
                               bg='#E8E8E8', highlightthickness=0)
        self.h_ruler.grid(row=0, column=1, sticky='ew')
        
        # 좌측 눈금자
        self.v_ruler = tk.Canvas(canvas_container, width=ruler_size,
                               bg='#E8E8E8', highlightthickness=0)
        self.v_ruler.grid(row=1, column=0, sticky='ns')
        
        # 캔버스 프레임
        canvas_frame = tk.Frame(canvas_container, bg=COLORS['border'], 
                              relief='solid', borderwidth=1)
        canvas_frame.grid(row=1, column=1, sticky='nsew')
        
        # 메인 캔버스
        self.canvas = tk.Canvas(canvas_frame, bg='#F0F0F0', highlightthickness=0)
        
        # 스크롤바 (세로만 사용)
        v_scroll = ttk.Scrollbar(canvas_frame, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=v_scroll.set)
        
        # 그리드 배치
        self.canvas.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_container.grid_rowconfigure(1, weight=1)
        canvas_container.grid_columnconfigure(1, weight=1)
        
        # 우클릭 메뉴
        self.context_menu = tk.Menu(self.window, tearoff=0)
        self.context_menu.add_command(label="선 삭제", command=self.delete_selected_point)
        self.context_menu.add_separator()
        # self.context_menu.add_command(label="여기서 분할", command=self.split_here)
        self.context_menu.add_command(label="균등 분할...", command=self.equal_split)
        
        # 이벤트 바인딩
        self.canvas.bind('<Button-1>', self.on_click)
        self.canvas.bind('<B1-Motion>', self.on_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_release)
        self.canvas.bind('<Motion>', self.on_hover)
        self.canvas.bind('<MouseWheel>', self.on_mousewheel)
        self.canvas.bind('<Control-MouseWheel>', self.on_ctrl_mousewheel)
        self.canvas.bind('<Button-3>', self.show_context_menu)
        self.canvas.bind('<Configure>', self.on_canvas_resize)
        
        # 키보드 단축키
        self.window.bind('<Control-z>', lambda e: self.undo())
        self.window.bind('<Control-y>', lambda e: self.redo())
        self.window.bind('<Delete>', lambda e: self.delete_selected_point())
        self.window.bind('<Control-a>', lambda e: self.select_all())
        self.window.bind('<Escape>', lambda e: self.deselect_all())
        self.window.bind('<Control-plus>', lambda e: self.zoom_delta(10))
        self.window.bind('<Control-minus>', lambda e: self.zoom_delta(-10))
        self.window.bind('<Control-0>', lambda e: self.set_zoom_ratio("100%"))
        
        # 백스페이스 키도 삭제 기능에 추가
        self.window.bind('<BackSpace>', lambda e: self.delete_selected_point())
        
        self.window.bind('<Destroy>', self.on_destroy)
        
        # 상태 변수
        self.snap_enabled = False
        self.snap_threshold = 10
        self.grid_size = 50
        self.show_grid = False
        
        self.load_image()
        self.update_rulers()
        
    def zoom_delta(self, delta):
        """줌 증감"""
        new_ratio = max(5, min(200, self.zoom_ratio + delta))
        self.set_zoom_ratio(f"{new_ratio}%")
        
    def zoom_fit(self):
        """화면에 맞춤"""
        if not self.img_original:
            return
            
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width > 1 and canvas_height > 1:
            scale_x = canvas_width / self.img_original.width
            scale_y = canvas_height / self.img_original.height
            scale = min(scale_x, scale_y) * 0.9  # 90% 여백
            
            new_ratio = int(scale * 100)
            new_ratio = max(5, min(200, new_ratio))
            self.set_zoom_ratio(f"{new_ratio}%")
            
    def toggle_snap(self):
        """스냅 토글"""
        self.snap_enabled = not self.snap_enabled
        status = "켜짐" if self.snap_enabled else "꺼짐"
        self.show_status_text(f"스냅: {status}")
        
    def auto_split(self):
        """자동 분할"""
        if not self.img_original:
            return
            
        # 자동 분할 다이얼로그
        dialog = tk.Toplevel(self.window)
        dialog.title("자동 분할")
        dialog.geometry("300x200")
        dialog.configure(bg=COLORS['bg_main'])
        dialog.transient(self.window)
        dialog.grab_set()
        
        # 중앙 배치
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # 옵션
        tk.Label(dialog, text="분할 방식을 선택하세요",
                font=('맑은 고딕', 11, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_main']).pack(pady=20)
        
        # 간격 분할
        interval_frame = tk.Frame(dialog, bg=COLORS['bg_main'])
        interval_frame.pack(pady=5)
        
        tk.Label(interval_frame, text="간격(px):",
                font=('맑은 고딕', 10),
                fg=COLORS['text_medium'], bg=COLORS['bg_main']).pack(side='left')
        
        interval_var = tk.StringVar(value="1200")
        interval_entry = tk.Entry(interval_frame, textvariable=interval_var,
                                width=10, font=('맑은 고딕', 10))
        interval_entry.pack(side='left', padx=5)
        
        def apply_interval():
            try:
                interval = int(interval_var.get())
                if interval <= 0:
                    raise ValueError
                    
                # 실행 취소 스택에 저장
                self.save_undo_state()
                
                # 분할점 생성
                self.cut_points = []
                for y in range(interval, self.img_original.height, interval):
                    self.cut_points.append(y)
                    
                self.draw_cut_lines()
                dialog.destroy()
                self.show_status_text(f"{len(self.cut_points)}개 분할점 생성")
                
            except ValueError:
                messagebox.showerror("오류", "올바른 숫자를 입력하세요")
        
        tk.Button(interval_frame, text="적용", command=apply_interval,
                font=('맑은 고딕', 9), bg=COLORS['primary'], fg='white',
                relief='flat', padx=15, pady=3).pack(side='left', padx=5)
        
        # 개수로 분할
        count_frame = tk.Frame(dialog, bg=COLORS['bg_main'])
        count_frame.pack(pady=5)
        
        tk.Label(count_frame, text="분할 개수:",
                font=('맑은 고딕', 10),
                fg=COLORS['text_medium'], bg=COLORS['bg_main']).pack(side='left')
        
        count_var = tk.StringVar(value="10")
        count_entry = tk.Entry(count_frame, textvariable=count_var,
                             width=10, font=('맑은 고딕', 10))
        count_entry.pack(side='left', padx=5)
        
        def apply_count():
            try:
                count = int(count_var.get())
                if count <= 0:
                    raise ValueError
                    
                # 실행 취소 스택에 저장
                self.save_undo_state()
                
                # 균등 분할
                interval = self.img_original.height // (count + 1)
                self.cut_points = []
                for i in range(1, count + 1):
                    self.cut_points.append(interval * i)
                    
                self.draw_cut_lines()
                dialog.destroy()
                self.show_status_text(f"{len(self.cut_points)}개 분할점 생성")
                
            except ValueError:
                messagebox.showerror("오류", "올바른 숫자를 입력하세요")
        
        tk.Button(count_frame, text="적용", command=apply_count,
                font=('맑은 고딕', 9), bg=COLORS['primary'], fg='white',
                relief='flat', padx=15, pady=3).pack(side='left', padx=5)
        
        # 취소 버튼
        tk.Button(dialog, text="취소", command=dialog.destroy,
                font=('맑은 고딕', 10), bg=COLORS['warning'], fg='white',
                relief='flat', padx=20, pady=5).pack(pady=20)
        
    def save_undo_state(self):
        """현재 상태를 실행 취소 스택에 저장"""
        current_state = self.cut_points.copy()
        
        # 현재 상태가 마지막 undo 상태와 다른 경우에만 저장
        if not self.undo_stack or current_state != self.undo_stack[-1]:
            self.undo_stack.append(current_state)
            self.redo_stack.clear()
            
            # 스택 크기 제한
            if len(self.undo_stack) > 50:
                self.undo_stack.pop(0)
            
    def undo(self, event=None):
        """실행 취소"""
        if len(self.undo_stack) > 1:  # 최소 2개의 상태가 있어야 undo 가능
            current_state = self.cut_points.copy()
            self.redo_stack.append(current_state)
            self.cut_points = self.undo_stack.pop()
            self.draw_cut_lines()
            self.show_status_text("실행 취소")
            
    def redo(self, event=None):
        """다시 실행"""
        if self.redo_stack:
            current_state = self.cut_points.copy()
            self.undo_stack.append(current_state)
            self.cut_points = self.redo_stack.pop()
            self.draw_cut_lines()
            self.show_status_text("다시 실행")
            
    def select_all(self):
        """모든 분할점 선택"""
        # 구현 예정
        pass
        
    def deselect_all(self):
        """선택 해제"""
        self.selected_point_idx = None
        self.draw_cut_lines()
        
    def split_here(self):
        """현재 위치에서 분할"""
        # 우클릭 위치에서 분할점 추가
        pass
        
    def equal_split(self):
        """균등 분할"""
        self.auto_split()
        
    def on_canvas_resize(self, event):
        """캔버스 크기 변경"""
        if self.img_display:
            self.update_display()
            
    def on_ctrl_mousewheel(self, event):
        """Ctrl + 마우스휠로 줌"""
        delta = event.delta / 120 if event.delta else 0
        self.zoom_delta(int(delta * 5))
        
    def update_rulers(self):
        """눈금자 업데이트"""
        if not self.img_display or not hasattr(self, 'h_ruler'):
            return
            
        # 수평 눈금자
        self.h_ruler.delete("all")
        scale = self.zoom_ratio / 100.0
        
        for i in range(0, self.img_original.width, 100):
            x = i * scale + self.x_offset
            self.h_ruler.create_line(x, 20, x, 30, fill='gray')
            if i % 500 == 0:
                self.h_ruler.create_line(x, 10, x, 30, fill='black')
                self.h_ruler.create_text(x, 5, text=str(i), font=('Arial', 8))
                
        # 수직 눈금자
        self.v_ruler.delete("all")
        
        for i in range(0, self.img_original.height, 100):
            y = i * scale + self.y_offset
            self.v_ruler.create_line(20, y, 30, y, fill='gray')
            if i % 500 == 0:
                self.v_ruler.create_line(10, y, 30, y, fill='black')
                self.v_ruler.create_text(5, y, text=str(i), font=('Arial', 8), angle=90)
                
    def choose_bg_color(self):
        """배경색 선택"""
        color = colorchooser.askcolor(title="배경색 선택", initialcolor=self.bg_color)
        if color[1]:
            self.set_bg_color(color[1])
    
    def set_zoom_ratio(self, ratio_str):
        """줌 비율 설정"""
        self.zoom_ratio = int(ratio_str.rstrip('%'))
        self.ratio_var.set(ratio_str)
        self.update_display()
        self.update_status()
        self.update_rulers()
        
        if PreviewWindow.keep_ratio_fixed:
            PreviewWindow.shared_zoom_ratio = self.zoom_ratio
    
    def set_bg_color(self, color):
        """배경색 설정"""
        self.bg_color = color
        if color != 'checkerboard':
            self.bg_color_btn.config(bg=color)
        else:
            self.bg_color_btn.config(bg='#E0E0E0')
        self.update_display()
        self.update_status()
        
        if PreviewWindow.keep_bg_fixed:
            PreviewWindow.shared_bg_color = self.bg_color
    
    def update_status(self):
        """상태 업데이트"""
        if not self.img_original or not self.status_label:
            return
            
        # 기본 상태 정보 업데이트
        self.status_label.config(text=self.get_status_text())
        
    def load_image(self):
        """이미지 로드"""
        try:
            # PSD/PSB 지원
            if self.file_row.path.suffix.lower() in ('.psd', '.psb'):
                if not PSDImage:
                    messagebox.showerror("오류", "PSD 지원 라이브러리가 설치되지 않았습니다.\n\npip install psd-tools")
                    return False
                self.img_original = load_psd_image(self.file_row.path)
            else:
                self.img_original = Image.open(self.file_row.path)
                
            self.update_display()
            
            # 기존 분할점 로드
            if self.file_row.pos.get().strip():
                points = [int(x.strip()) for x in self.file_row.pos.get().split(',') if x.strip()]
                self.cut_points = sorted(list(set(points)))
                self.draw_cut_lines()
                
            self.update_status()
            
        except Exception as e:
            messagebox.showerror("오류", f"이미지 로드 실패: {e}")
            return False
            
        return True

    def update_display(self):
        """디스플레이 업데이트"""
        if not self.img_original or not self.canvas:
            return
            
        # 줌 적용
        orig_w, orig_h = self.img_original.size
        scale_factor = self.zoom_ratio / 100.0
        
        new_w = int(orig_w * scale_factor)
        new_h = int(orig_h * scale_factor)
        
        # 리사이즈
        if scale_factor == 1.0:
            resized_img = self.img_original.copy()
        else:
            resample = Image.Resampling.LANCZOS
            resized_img = self.img_original.resize((new_w, new_h), resample)
        
        # 배경 적용
        if self.bg_color == 'checkerboard':
            bg_img = create_checkerboard(new_w, new_h, max(10, int(20 * scale_factor)))
        else:
            try:
                bg_color_rgb = hex_to_rgb(self.bg_color)
                bg_img = Image.new('RGB', (new_w, new_h), bg_color_rgb)
            except:
                bg_img = Image.new('RGB', (new_w, new_h), (255, 255, 255))
        
        # 이미지 합성
        if resized_img.mode == 'RGBA':
            bg_img.paste(resized_img, (0, 0), resized_img)
        else:
            bg_img = resized_img
            
        self.img_display = bg_img
        self.photo = ImageTk.PhotoImage(self.img_display)
        
        # 캔버스 배경색
        if self.bg_color == 'checkerboard':
            canvas_bg = '#F0F0F0'
        else:
            canvas_bg = self.bg_color
        self.canvas.configure(bg=canvas_bg)
        
        # 중앙 정렬 계산
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        self.x_offset = max(0, (canvas_width - new_w) // 2)
        self.y_offset = max(0, (canvas_height - new_h) // 2)
        
        # 스크롤 영역
        scroll_width = max(canvas_width, new_w + self.x_offset * 2)
        scroll_height = max(canvas_height, new_h + self.y_offset * 2)
        self.canvas.configure(scrollregion=(0, 0, scroll_width, scroll_height))
        
        # 이미지 표시
        self.canvas.delete("all")
        self.canvas.create_image(self.x_offset, self.y_offset, anchor='nw', image=self.photo)
        
        # 분할선 다시 그리기
        self.draw_cut_lines()
    
    def on_click(self, event):
        """클릭 이벤트"""
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        
        # 이미지 좌표로 변환
        image_x = canvas_x - self.x_offset
        image_y = canvas_y - self.y_offset
        
        # 이미지 영역 확인
        if not (0 <= image_x <= self.img_display.width):
            self.selected_point_idx = None
            return
        
        # 기존 분할선 클릭 확인
        scale_factor = self.zoom_ratio / 100.0
        clicked_line = None
        
        for i, point in enumerate(self.cut_points):
            display_y = point * scale_factor + self.y_offset
            if abs(canvas_y - display_y) <= 12:
                clicked_line = i
                break
        
        if clicked_line is not None:
            # 선 선택
            self.selected_point_idx = clicked_line
            self.dragging = True
            self.last_y = canvas_y
            self.canvas.config(cursor="sb_v_double_arrow")
            self.draw_cut_lines()
        else:
            # 새 분할점 추가
            original_y = int((canvas_y - self.y_offset) / scale_factor)
            
            # 스냅 적용
            if self.snap_enabled:
                original_y = round(original_y / self.grid_size) * self.grid_size
            
            if 0 <= original_y <= self.img_original.height:
                # 중복 체크
                duplicate = False
                for existing_point in self.cut_points:
                    if abs(existing_point - original_y) <= 2:
                        duplicate = True
                        break
                
                if not duplicate:
                    self.save_undo_state()
                    self.cut_points.append(original_y)
                    self.cut_points = sorted(list(set(self.cut_points)))
                    self.draw_cut_lines()
            
            self.selected_point_idx = None
            self.draw_cut_lines()
    
    def on_drag(self, event):
        """드래그 이벤트"""
        if not self.dragging or self.selected_point_idx is None:
            return
            
        canvas_y = self.canvas.canvasy(event.y)
        scale_factor = self.zoom_ratio / 100.0
        
        # 원본 좌표로 변환
        new_original_y = int((canvas_y - self.y_offset) / scale_factor)
        
        # 스냅 적용
        if self.snap_enabled:
            new_original_y = round(new_original_y / self.grid_size) * self.grid_size
        
        # 범위 제한
        new_original_y = max(0, min(self.img_original.height, new_original_y))
        
        # 업데이트
        if self.selected_point_idx < len(self.cut_points):
            self.cut_points[self.selected_point_idx] = new_original_y
            self.cut_points = sorted(list(set(self.cut_points)))
            
            try:
                self.selected_point_idx = self.cut_points.index(new_original_y)
            except ValueError:
                self.dragging = False
                self.selected_point_idx = None
                self.canvas.config(cursor="")
                return
            
            self.draw_cut_lines()
    
    def on_release(self, event):
        """릴리즈 이벤트"""
        if self.dragging:
            self.save_undo_state()
        self.dragging = False
        self.selected_point_idx = None
        self.canvas.config(cursor="")
    
    def show_context_menu(self, event):
        """우클릭 메뉴"""
        canvas_y = self.canvas.canvasy(event.y)
        scale_factor = self.zoom_ratio / 100.0
        
        # 클릭한 위치 저장
        self.context_click_y = int((canvas_y - self.y_offset) / scale_factor)
        
        # 선 근처 확인
        for i, point in enumerate(self.cut_points):
            display_y = point * scale_factor + self.y_offset
            if abs(canvas_y - display_y) <= 12:
                self.selected_point_idx = i
                self.context_menu.post(event.x_root, event.y_root)
                return
        
        self.selected_point_idx = None
        self.context_menu.post(event.x_root, event.y_root)
    
    def on_hover(self, event):
        """호버 이벤트"""
        if self.dragging:
            return
            
        canvas_y = self.canvas.canvasy(event.y)
        scale_factor = self.zoom_ratio / 100.0
        
        # 분할선 근처 확인
        near_line = False
        for point in self.cut_points:
            display_y = point * scale_factor + self.y_offset
            if abs(canvas_y - display_y) <= 12:
                near_line = True
                break
        
        # 커서 변경
        if near_line:
            self.canvas.config(cursor="sb_v_double_arrow")
        else:
            self.canvas.config(cursor="")
    
    def on_mousewheel(self, event):
        """마우스휠 스크롤"""
        # Windows
        if event.delta:
            delta = event.delta
        # Linux
        elif event.num == 4:
            delta = 120
        elif event.num == 5:
            delta = -120
        else:
            return
        
        # Shift 키가 눌려있으면 수평 스크롤
        if event.state & 0x0001:  # Shift
            self.canvas.xview_scroll(int(-1 * (delta / 120)), "units")
        else:
            self.canvas.yview_scroll(int(-1 * (delta / 120)), "units")
            
    def draw_cut_lines(self):
        """분할선 그리기"""
        if not self.canvas or not self.img_display:
            return
            
        # 기존 분할선 제거
        self.canvas.delete("cut_line")
        self.canvas.delete("cut_number")
        self.canvas.delete("cut_label")
        
        # 새 분할선 그리기
        scale_factor = self.zoom_ratio / 100.0
        
        for i, point in enumerate(self.cut_points):
            display_y = point * scale_factor + self.y_offset
            
            # 선택 상태 확인
            is_selected = (self.selected_point_idx == i)
            line_color = COLORS['error'] if is_selected else COLORS['warning']
            line_width = 3 if is_selected else 2
            
            # 분할선
            self.canvas.create_line(
                self.x_offset, display_y, 
                self.img_display.width + self.x_offset, display_y,
                fill=line_color, width=line_width, tags="cut_line"
            )
            
            # 라벨
            label_x = self.x_offset + self.img_display.width + 10
            
            # 번호 배경
            bbox = self.canvas.create_text(
                label_x, display_y,
                text=f" #{i + 1} Y:{point:,} ",
                fill='white', anchor='w',
                font=('맑은 고딕', 10, 'bold'),
                tags="cut_number"
            )
            
            # 배경 박스
            coords = self.canvas.bbox(bbox)
            if coords:
                self.canvas.create_rectangle(
                    coords[0] - 2, coords[1] - 2,
                    coords[2] + 2, coords[3] + 2,
                    fill=line_color, outline='', tags="cut_label"
                )
                
            # 텍스트 다시 그리기 (배경 위에)
            self.canvas.create_text(
                label_x, display_y,
                text=f" #{i + 1} Y:{point:,} ",
                fill='white', anchor='w',
                font=('맑은 고딕', 10, 'bold'),
                tags="cut_number"
            )
            
        # 그리드 표시 (옵션)
        if self.show_grid:
            self.draw_grid()
    
    def draw_grid(self):
        """그리드 그리기"""
        # 구현 예정
        pass
    
    def delete_selected_point(self, event=None):
        """선택된 분할점 삭제"""
        if self.selected_point_idx is not None and 0 <= self.selected_point_idx < len(self.cut_points):
            self.save_undo_state()
            point_number = self.selected_point_idx + 1
            del self.cut_points[self.selected_point_idx]
            
            self.selected_point_idx = None
            self.dragging = False
            self.canvas.config(cursor="")
            
            self.draw_cut_lines()
            self.show_status_text(f"#{point_number} 분할선 삭제됨")
    
    def clear_points(self):
        """분할점 초기화"""
        if self.cut_points and messagebox.askyesno("확인", "모든 분할점을 삭제하시겠습니까?"):
            self.save_undo_state()
            self.cut_points.clear()
            self.selected_point_idx = None
            self.dragging = False
            self.canvas.config(cursor="")
            self.draw_cut_lines()
            self.show_status_text("모든 분할점 삭제됨")
            
    def apply_points(self):
        """분할점 적용"""
        if self.cut_points:
            points_str = ','.join(map(str, self.cut_points))
            self.file_row.pos.set(points_str)
            messagebox.showinfo("적용 완료", 
                f"{len(self.cut_points)}개 분할점이 적용되었습니다.\n\n"
                f"이제 '분할' 버튼을 클릭하여 이미지를 분할할 수 있습니다.")
        self.window.destroy()
        
    def show_status_text(self, text, duration=2000):
        """상태 텍스트 표시"""
        if not self.message_label:
            return
            
        # 상태 메시지 포맷팅
        status_text = f"《 {text} 》"
        self.message_label.config(text=status_text)
        
        # 이전 타이머가 있다면 취소
        if hasattr(self, '_status_timer') and self._status_timer:
            self.window.after_cancel(self._status_timer)
            
        # duration이 0보다 크면 타이머 설정
        if duration > 0:
            self._status_timer = self.window.after(duration, lambda: self.message_label.config(text=""))
    
    def on_destroy(self, event=None):
        """창 닫기"""
        if event and event.widget != self.window:
            return
        self.selected_point_idx = None
        self.dragging = False
        self.window = None
        self.canvas = None
        if self.img_original:
            self.img_original.close()

    def get_status_text(self):
        """현재 상태 정보 텍스트 반환"""
        if not self.img_original:
            return ""
            
        status = []
        
        # 이미지 크기
        status.append(f"크기: {self.img_original.width}×{self.img_original.height}")
        
        # 줌 비율
        status.append(f"줌: {self.zoom_ratio}%")
        
        # 배경색
        bg_display = self.bg_color if self.bg_color != 'checkerboard' else '체크무늬'
        status.append(f"배경: {bg_display}")
        
        # 분할점 개수
        status.append(f"분할점: {len(self.cut_points)}개")
        
        return " | ".join(status)

# ===== 메인 파일 행 클래스 =====
class FileRow(tk.Frame):
    """파일 행 위젯"""
    def __init__(self, master, idx: int):
        super().__init__(master, bg=COLORS['bg_section'], relief='solid', 
                        borderwidth=1, padx=10, pady=8)
        self.app = None
        self.idx = idx
        self.file = tk.StringVar()
        self.path = Path()
        self.pos = tk.StringVar()

        self.state = tk.StringVar()
        self.hist: Dict[str, int] = {}
        self.platform_var = tk.StringVar(value="naver")  # 기본값 설정
        self.preview_window = PreviewWindow(master, self)
        
        # 분할용 파일명 변수들 추가
        self.split_filename = tk.StringVar(value="")
        self.number_digits = tk.StringVar(value="3")

        self._build_ui()

    def _build_ui(self):
        """UI 구성"""
        # 번호
        num_label = tk.Label(self, text=f"{self.idx + 1:02d}", 
                           font=('맑은 고딕', 10, 'bold'), 
                           fg=COLORS['primary'], bg=COLORS['bg_section'], width=3)
        num_label.grid(row=0, column=0, sticky='w', padx=(0, 8))
        
        # 파일명
        file_label = tk.Label(self, textvariable=self.file, width=40, 
                            font=('맑은 고딕', 9), fg=COLORS['text_dark'], 
                            bg=COLORS['bg_section'], anchor='w')
        file_label.grid(row=0, column=1, sticky='w', padx=(0, 8))
        
        # 툴팁
        self.tooltip = None
        file_label.bind('<Enter>', self._show_tooltip)
        file_label.bind('<Leave>', self._hide_tooltip)
        self.file_label = file_label

        # 위치 입력
        self.pos_entry = tk.Entry(self, textvariable=self.pos, width=30, 
                                font=('맑은 고딕', 11), relief='solid', borderwidth=1)
        self.pos_entry.grid(row=0, column=2, sticky='ew', padx=(0, 8), pady=4)
        self.pos_entry.bind('<Tab>', self._tab_next)

        # 분할설정 버튼
        preview_btn = tk.Button(self, text='분할설정', command=self.show_preview, 
                              font=('맑은 고딕', 10), bg=COLORS['primary'], fg='white',
                              relief='flat', padx=12, pady=6)
        preview_btn.grid(row=0, column=3, padx=(0, 8))
        
        # 호버 효과
        preview_btn.bind('<Enter>', lambda e: preview_btn.configure(bg='#3B7DD8'))
        preview_btn.bind('<Leave>', lambda e: preview_btn.configure(bg=COLORS['primary']))

        # 파일명 설정 프레임
        filename_frame = tk.Frame(self, bg=COLORS['bg_hover'], relief='solid', 
                                borderwidth=1, padx=6, pady=5)
        filename_frame.grid(row=0, column=4, sticky='nsew', padx=(0, 8))

        # 상단 프레임 (파일명 입력)
        top_frame = tk.Frame(filename_frame, bg=COLORS['bg_hover'])
        top_frame.pack(fill='x', pady=(0, 3))

        # 파일명 라벨
        filename_label = tk.Label(top_frame, text='파일명:', 
                                font=('맑은 고딕', 8),
                                fg=COLORS['text_dark'], bg=COLORS['bg_hover'])
        filename_label.pack(side='left', padx=(0, 3))

        # 파일명 입력창
        self.filename_entry = tk.Entry(top_frame, textvariable=self.split_filename, 
                                     width=13, font=('맑은 고딕', 10), 
                                     relief='solid', borderwidth=1)
        self.filename_entry.pack(side='left', padx=(0, 5))

        # 하단 프레임 (자릿수 설정)
        bottom_frame = tk.Frame(filename_frame, bg=COLORS['bg_hover'])
        bottom_frame.pack(fill='x')

        # 번호 자릿수 라벨
        digits_label = tk.Label(bottom_frame, text='자릿수:', 
                              font=('맑은 고딕', 8),
                              fg=COLORS['text_dark'], bg=COLORS['bg_hover'])
        digits_label.pack(side='left', padx=(0, 3))

        # 번호 자릿수 선택
        digits_combo = ttk.Combobox(bottom_frame, textvariable=self.number_digits,
                                  values=['2', '3', '4', '5'], width=3, state='readonly',
                                  font=('맑은 고딕', 8))
        digits_combo.pack(side='left', padx=(0, 5))

        # 예시 라벨
        self.example_label = tk.Label(bottom_frame, text='', 
                                    font=('맑은 고딕', 7),
                                    fg=COLORS['text_light'], bg=COLORS['bg_hover'])
        self.example_label.pack(side='left', padx=(5, 0))

        # 파일명 변경 시 예시 업데이트
        self.split_filename.trace('w', self._update_filename_example)
        self.number_digits.trace('w', self._update_filename_example)

        # 툴팁
        self.filename_tooltip = None
        filename_frame.bind('<Enter>', self._show_filename_tooltip)
        filename_frame.bind('<Leave>', self._hide_filename_tooltip)

        # 분할 버튼
        split_btn = tk.Button(self, text='⚡분할', command=self._do_split, 
                            font=('맑은 고딕', 10), bg=COLORS['accent'], fg='white',
                            relief='flat', padx=12, pady=6)
        split_btn.grid(row=0, column=5, padx=(0, 8))
        
        # 호버 효과
        split_btn.bind('<Enter>', lambda e: split_btn.configure(bg=COLORS['success']))
        split_btn.bind('<Leave>', lambda e: split_btn.configure(bg=COLORS['accent']))

        # 상태
        state_label = tk.Label(self, textvariable=self.state, width=6, 
                             font=('맑은 고딕', 8, 'bold'), fg=COLORS['accent'],
                             bg=COLORS['bg_section'])
        state_label.grid(row=0, column=6, sticky='e', padx=(0, 8))

        # 삭제 버튼 (크기와 위치 개선)
        delete_btn = tk.Button(self, text='×', command=self._remove_row,
                            font=('맑은 고딕', 10, 'bold'), bg=COLORS['error'],
                            fg='white', relief='flat', width=3, height=1, padx=8)
        delete_btn.grid(row=0, column=7, padx=(5, 5), sticky='e')
        
        # 호버 효과
        delete_btn.bind('<Enter>', lambda e: delete_btn.configure(bg='#ff4444'))
        delete_btn.bind('<Leave>', lambda e: delete_btn.configure(bg=COLORS['error']))

        # 컬럼 가중치 (X 버튼이 더 잘 보이도록 조정)
        weights = [2, 22, 16, 8, 18, 8, 6, 3]  # [번호, 파일명, 분할위치, 분할설정, 파일명설정, 분할, 상태, 삭제버튼]
        for c, w in enumerate(weights):
            self.columnconfigure(c, weight=w)
        self.grid(sticky='ew', pady=5)

    def _remove_row(self):
        """행 삭제"""
        if self.app:
            self.app.rows.remove(self)
            self.destroy()
            
            # 번호 재정렬
            for i, row in enumerate(self.app.rows):
                row.idx = i
                row.grid(row=i)
                
                # 번호 라벨 업데이트
                for child in row.winfo_children():
                    if isinstance(child, tk.Label) and child.cget('width') == 3:
                        child.configure(text=f"{i + 1:02d}")
                        break

    def show_preview(self):
        """미리보기 창 표시"""
        self.preview_window.show()

    def _update_filename_example(self, *args):
        """파일명 예시 업데이트"""
        filename = self.split_filename.get().strip()
        digits = int(self.number_digits.get())
        
        # PNG 체크박스 상태에 따라 확장자 결정
        ext = ".png" if (self.app and self.app.save_as_png.get()) else ".jpg"
        
        if filename:
            # 파일명 정리
            clean_name = self._clean_split_filename(filename)
            example = f"예: {clean_name}_{1:0{digits}d}{ext}"
        else:
            # 원본 파일명 사용
            if self.path and self.path.name:
                base_name = self.path.stem
                example = f"예: {base_name}_{1:0{digits}d}{ext}"
            else:
                example = f"예: image_{1:0{digits}d}{ext}"
        
        if hasattr(self, 'example_label'):
            self.example_label.config(text=example)
    
    def _clean_split_filename(self, filename):
        """분할용 파일명 정리"""
        # 금지된 문자 제거
        forbidden_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in forbidden_chars:
            filename = filename.replace(char, '_')
        
        # 공백을 언더스코어로 변경
        filename = filename.replace(' ', '_')
        
        # 앞뒤 공백 및 점 제거
        filename = filename.strip(' ._')
        
        # 빈 문자열이면 기본값 사용
        if not filename:
            filename = "image"
        
        return filename

    def _tab_next(self, event):
        """다음 입력 필드로 이동"""
        nxt = (self.app.rows.index(self) + 1) % len(self.app.rows)
        self.app.rows[nxt].pos_entry.focus_set()
        return "break"

    def set_file(self, name: str, path: Path):
        """파일 설정"""
        try:
            info = get_image_info(path)
            if info:
                display_text = f"{path.name} ({format_file_size(info.size_bytes)}, {info.width}×{info.height})"
            else:
                display_text = f"{path.name} ({format_file_size(path.stat().st_size)})"
        except:
            display_text = path.name
            
        self.file.set(display_text)
        self.path = path
        self.pos.set('')
        self.state.set('')
        self.hist.clear()
        
        # 파일명 예시 업데이트
        self._update_filename_example()

    def clear(self):
        """초기화"""
        self.file.set('')
        self.path = Path()
        self.pos.set('')
        self.state.set('')
        self.hist.clear()
        
        # 파일명 예시 업데이트
        self._update_filename_example()

    def has_input(self):
        """입력값 확인"""
        return self.path and self.pos.get().strip()

    def _parse(self):
        """입력값 파싱"""
        txt = self.pos.get().replace(' ', '')
        if not txt:
            messagebox.showerror('오류', '분할 위치를 입력해주세요.')
            return None, None, 'list'
        try:
            nums = [int(v) for v in txt.split(',') if v]
        except Exception:
            messagebox.showerror('오류', '숫자만 입력 가능합니다.')
            return None, None, 'list'
        if any(nums[i] >= nums[i + 1] for i in range(len(nums) - 1)):
            messagebox.showerror('오류', '오름차순으로 입력해주세요.')
            return None, None, 'list'
        return nums, txt, 'list'

    def _do_split(self):
        """분할 실행"""
        if not self.path or not self.app:
            messagebox.showerror("오류", "파일이 선택되지 않았습니다.")
            return
            
        val, key, mode = self._parse()
        if val is None:
            messagebox.showerror("오류", "분할 위치가 설정되지 않았습니다.")
            return
            
        q = self.app.quality.get()
        out = self.app.ensure_out()
        if not out:
            messagebox.showerror("오류", "출력 폴더가 설정되지 않았습니다.")
            return
            
        save_as_png = self.app.save_as_png.get()

        combo = f"{mode}|{key}|{q}"
        if combo in self.hist:
            self.state.set('SKIP')
            return
            
        ver = 0 if not self.hist else max(self.hist.values()) + 1
        self.hist[combo] = ver

        # 진행률 다이얼로그
        progress_dialog = ProgressDialog(self.app, "이미지 분할 중...", 
                                       f"{self.path.name} 처리 중...")
        
        def progress_callback(value):
            progress_dialog.update_progress(value)
            
        def split_task():
            try:
                # 사용자 정의 파일명 적용
                custom_filename = self.split_filename.get().strip()
                digits = int(self.number_digits.get())
                
                split_image_at_points_custom(self.path, val, out, q, ver, 
                                           save_as_png, None, progress_callback,
                                           custom_filename, digits)
                    
                self.app.after(0, lambda: self.state.set('OK' if ver == 0 else f"v{ver:03d}"))
                self.app.after(0, progress_dialog.destroy)
                
            except Exception as e:
                self.app.after(0, lambda: messagebox.showerror('실패', str(e)))
                self.app.after(0, lambda: self.state.set('ERR'))
                self.app.after(0, progress_dialog.destroy)
        
        # 스레드에서 실행
        thread = threading.Thread(target=split_task)
        thread.daemon = True
        thread.start()

    def _show_tooltip(self, event):
        """툴팁 표시"""
        if self.path:
            x, y, _, _ = self.file_label.bbox("insert")
            x += self.file_label.winfo_rootx() + 25
            y += self.file_label.winfo_rooty() + 25

            self._hide_tooltip(event)

            self.tooltip = tk.Toplevel(self)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.wm_geometry(f"+{x}+{y}")

            tooltip_text = f"파일명: {self.path.name}\n경로: {self.path.parent}"
            label = tk.Label(self.tooltip, text=tooltip_text,
                           justify='left', background="#ffffe0",
                           relief='solid', borderwidth=1,
                           font=('맑은 고딕', 8), padx=5, pady=3)
            label.pack()

    def _hide_tooltip(self, event):
        """툴팁 숨기기"""
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def _show_interval_tooltip(self, event):
        """간격 툴팁 표시"""
        x = event.widget.winfo_rootx()
        y = event.widget.winfo_rooty() + event.widget.winfo_height() + 5

        self._hide_interval_tooltip(event)

        self.interval_tooltip = tk.Toplevel(self)
        self.interval_tooltip.wm_overrideredirect(True)
        self.interval_tooltip.wm_geometry(f"+{x}+{y}")

        tooltip_text = (
            "일정 간격 분할 모드\n\n"
            "• 체크박스를 선택하면 일정한 간격으로 이미지를 분할합니다\n"
            "• 간격(px)에 원하는 픽셀 값을 입력하세요\n"
           
        )
        
        label = tk.Label(self.interval_tooltip, text=tooltip_text,
                        justify='left', background="#ffffe0",
                        relief='solid', borderwidth=1,
                        font=('맑은 고딕', 9), padx=10, pady=5)
        label.pack()

    def _show_filename_tooltip(self, event):
        """파일명 툴팁 표시"""
        x = event.widget.winfo_rootx()
        y = event.widget.winfo_rooty() + event.widget.winfo_height() + 5

        self._hide_filename_tooltip(event)

        self.filename_tooltip = tk.Toplevel(self)
        self.filename_tooltip.wm_overrideredirect(True)
        self.filename_tooltip.wm_geometry(f"+{x}+{y}")

        tooltip_text = (
            "파일명 및 번호 설정\n\n"
            "• 파일명: 분할된 파일들의 기본 이름을 설정합니다\n"
            "• 번호: 파일명 뒤에 붙을 번호의 자릿수를 선택합니다\n"
            "• 빈칸: 원본 파일명을 사용합니다\n"
            "• 예시가 실시간으로 표시됩니다"
        )
        
        label = tk.Label(self.filename_tooltip, text=tooltip_text,
                        justify='left', background="#ffffe0",
                        relief='solid', borderwidth=1,
                        font=('맑은 고딕', 9), padx=10, pady=5)
        label.pack()

    def _hide_filename_tooltip(self, event):
        """파일명 툴팁 숨기기"""
        if self.filename_tooltip:
            self.filename_tooltip.destroy()
            self.filename_tooltip = None

# ===== 메인 애플리케이션 =====
class App(tk.Frame):
    """메인 애플리케이션"""
    def __init__(self, master=None):
        super().__init__(master, bg=COLORS['bg_main'])
        self.pack(fill='both', expand=True)
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        
        master.configure(bg=COLORS['bg_main'])

        # 설정 로드
        self.config = ConfigManager.load()

        # 변수 초기화
        self.in_dir = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(unique_dir(BASE_OUT)))
        self.quality = tk.StringVar(value=self.config.get('quality', '무손실'))
        self.merge_dir = tk.StringVar()
        self.save_as_png = tk.BooleanVar(value=self.config.get('save_as_png', False))
        self.merge_filename = tk.StringVar(value="merged_images")
        self.split_filename = tk.StringVar(value="")  # 분할용 파일명
        self.number_digits = tk.StringVar(value="3")  # 번호 자릿수
        
        # 크기 조정 관련 변수
        self.resize_dir = tk.StringVar()
        self.target_width = tk.StringVar(value="800")  # 기본값: 네이버 웹툰
        self.resize_quality = tk.StringVar(value="고품질")  # 리샘플링 품질
        self.add_suffix = tk.BooleanVar(value=True)  # 파일명에 접미사 추가 여부
        self.resize_status = tk.StringVar(value="")
        
        # 상태 변수
        self.merge_status = tk.StringVar(value="")
        self.merge_btn = None
        self.resize_btn = None
        
        # 파일 행 리스트
        self.rows = []

        # 파일 뷰어
        self.split_file_viewer = FileListViewer(master, "분할할 파일 목록")
        self.split_file_viewer.set_callback(self._update_file_rows)
        self.merge_file_viewer = FileListViewer(master, "합칠 파일 목록")
        self.resize_file_viewer = FileListViewer(master, "크기 조정할 파일 목록")
        
        self._build()
        self._logo()
        

            
        # 종료 시 설정 저장
        master.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        """UI 구성"""
        # 메인 컨테이너
        main_container = tk.Frame(self, bg=COLORS['bg_main'])
        main_container.pack(fill='both', expand=True, padx=20, pady=20)

        # 탭 컨트롤
        notebook = ttk.Notebook(main_container)
        notebook.pack(fill='both', expand=True)
        
        # 스타일 설정
        style = ttk.Style()
        style.configure('TNotebook', background=COLORS['bg_main'])
        style.configure('TNotebook.Tab', padding=[20, 8], font=('맑은 고딕', 9))
        style.map('TNotebook.Tab',
            background=[('selected', COLORS['bg_main']), ('!selected', COLORS['bg_hover'])],
            foreground=[('selected', COLORS['text_dark']), ('!selected', COLORS['text_medium'])],
            font=[('selected', ('맑은 고딕', 10, 'bold')), ('!selected', ('맑은 고딕', 9))],
            padding=[('selected', [20, 10]), ('!selected', [20, 8])]
        )

        # 분할 탭
        split_tab = tk.Frame(notebook, bg=COLORS['bg_main'])
        notebook.add(split_tab, text="이미지 분할")
        self._build_split_tab(split_tab)

        # 합치기 탭
        merge_tab = tk.Frame(notebook, bg=COLORS['bg_main'])
        notebook.add(merge_tab, text="이미지 합치기")
        self._build_merge_tab(merge_tab)

        # 크기 조정 탭
        resize_tab = tk.Frame(notebook, bg=COLORS['bg_main'])
        notebook.add(resize_tab, text="크기 조정")
        self._build_resize_tab(resize_tab)



        # 푸터
        footer_text = (
            "제작: 악어스튜디오 경영기획부 | 버전 10.0 | 문의: hyo@akeostudio.com | "
            "© 2025 Akeo Studio • Free Distribution • akeostudio.com"
        )
        tk.Label(main_container, text=footer_text, font=('맑은 고딕', 9), 
               fg=COLORS['text_light'], bg=COLORS['bg_main']).pack(fill='x', pady=(10, 0))

    def _build_split_tab(self, parent):
        """분할 탭 구성"""
        # 분할 섹션
        split_section = tk.LabelFrame(parent, text=" 이미지 분할 ", 
                                    font=('맑은 고딕', 11, 'bold'), fg=COLORS['text_dark'],
                                    bg=COLORS['bg_section'], relief='solid', borderwidth=1)
        split_section.pack(fill='both', expand=True, padx=15, pady=15)
        split_section.configure(padx=15, pady=15)

        # 입력 프레임
        input_frame = tk.Frame(split_section, bg=COLORS['bg_section'])
        input_frame.pack(fill='x', pady=(0, 15))
        
        tk.Label(input_frame, text="입력 폴더:", font=('맑은 고딕', 10, 'bold'),
               fg=COLORS['text_dark'], bg=COLORS['bg_section']).grid(row=0, column=0, sticky='w')
        
        in_entry = tk.Entry(input_frame, textvariable=self.in_dir, font=('맑은 고딕', 12),
                          relief='solid', borderwidth=1)
        in_entry.grid(row=0, column=1, sticky='ew', padx=(10, 10), pady=4)
        
        input_frame.columnconfigure(1, weight=1)
        
        browse_btn = tk.Button(input_frame, text="📁 찾기", command=self._pick_in, 
                             font=('맑은 고딕', 10), bg=COLORS['primary'], fg='white',
                             relief='flat', padx=15, pady=5)
        browse_btn.grid(row=0, column=2, padx=(0, 10))
        
        # 툴팁 추가 (호버 효과 포함)
        ToolTip(browse_btn, "이미지가 들어있는 폴더를 선택합니다.\n선택된 폴더의 모든 이미지 파일이 자동으로 로드됩니다.", 
                hover_color='#3B7DD8', normal_color=COLORS['primary'])

        file_list_btn = tk.Button(input_frame, text="📄 파일 목록", command=self._show_split_files,
                                font=('맑은 고딕', 10), bg=COLORS['secondary'], fg='white',
                                relief='flat', padx=15, pady=5)
        file_list_btn.grid(row=0, column=3)
        
        # 툴팁 추가 (호버 효과 포함)
        ToolTip(file_list_btn, "선택된 폴더의 파일 목록을 자세히 확인합니다.\n개별 파일을 제외하거나 순서를 변경할 수 있습니다.", 
                hover_color='#6B58D3', normal_color=COLORS['secondary'])

        # 파일 리스트 헤더 (숨김 처리)
        # header_row = tk.Frame(split_section, bg=COLORS['bg_section'])
        # header_row.pack(fill='x', pady=(0, 10))
        
        # headers = ["No", "파일명", "분할 위치", "분할설정", "파일명 설정", "실행", "상태", ""]
        
        # for i, header in enumerate(headers):
        #     if header:
        #         label = tk.Label(header_row, text=header, font=('맑은 고딕', 9, 'bold'), 
        #                        fg=COLORS['text_medium'], bg=COLORS['bg_section'])
        #         label.grid(row=0, column=i, sticky='w', padx=5)
        
        # 파일 행 스크롤 영역
        scroll_frame = tk.Frame(split_section, bg=COLORS['bg_section'])
        scroll_frame.pack(fill='both', expand=True)
        
        # 캔버스와 스크롤바
        canvas = tk.Canvas(scroll_frame, bg=COLORS['bg_section'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_frame, orient='vertical', command=canvas.yview)
        
        self.rows_frame = tk.Frame(canvas, bg=COLORS['bg_section'])
        self.rows_frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        
        canvas.create_window((0, 0), window=self.rows_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # 초기 안내 메시지
        self.guide_label = tk.Label(self.rows_frame, 
                                   text="📌 이미지 분할 사용법\n\n"
                                        "1. 위의 '📁 찾기' 버튼으로 이미지가 있는 폴더를 선택해주세요\n"
                                        "2. 또는 '📄 파일 목록' 버튼으로 개별 파일을 선택/제외할 수 있습니다\n"
                                        "3. 폴더 선택 후 각 이미지별로 분할 설정을 할 수 있습니다\n"
                                        "4. 분할 위치는 '미리보기' 버튼으로 시각적으로 설정 가능합니다\n\n"
                                        "💡 지원 형식: JPG, PNG, WebP, PSD, PSB 등 주요 이미지 파일",
                                   font=('맑은 고딕', 10), fg=COLORS['text_medium'], 
                                   bg=COLORS['bg_section'], justify='left', 
                                   relief='flat', padx=20, pady=40)
        self.guide_label.pack(expand=True, fill='both')
            


        # 설정 및 출력
        settings_frame = tk.LabelFrame(split_section, text=" 저장 설정 ", 
                                     font=('맑은 고딕', 10, 'bold'), fg=COLORS['text_dark'],
                                     bg=COLORS['bg_section'], relief='solid', borderwidth=1)
        settings_frame.pack(fill='x', pady=(15, 0))
        settings_frame.configure(padx=15, pady=10)
        
        # 첫 번째 행: 품질과 형식
        settings_row1 = tk.Frame(settings_frame, bg=COLORS['bg_section'])
        settings_row1.pack(fill='x', pady=(0, 8))
        
        tk.Label(settings_row1, text="품질:", font=('맑은 고딕', 11, 'bold'),
               fg=COLORS['text_dark'], bg=COLORS['bg_section']).pack(side='left', padx=(0, 10))
        
        quality_values = ['무손실', 'High', 'Medium', 'Low']
        quality_menu = ttk.OptionMenu(settings_row1, self.quality, self.quality.get(), *quality_values)
        quality_menu.pack(side='left', padx=(0, 30))

        png_check = tk.Checkbutton(settings_row1, text="PNG로 저장 (무손실, 큰 파일크기)", 
                                 variable=self.save_as_png,
                                 font=('맑은 고딕', 10), fg=COLORS['text_dark'], 
                                 bg=COLORS['bg_section'],
                                 selectcolor=COLORS['bg_section'])
        png_check.pack(side='left')
        
        # PNG 체크박스 변경 시 파일명 예시 업데이트
        self.save_as_png.trace('w', self._update_all_filename_examples)
        
        # 목표 크기 변경 시 상태 업데이트
        self.target_width.trace('w', lambda *args: self.update_resize_status() if hasattr(self, 'resize_btn') else None)
        
        # 두 번째 행: 저장 폴더
        settings_row2 = tk.Frame(settings_frame, bg=COLORS['bg_section'])
        settings_row2.pack(fill='x')
        settings_row2.grid_columnconfigure(1, weight=1)
        
        tk.Label(settings_row2, text="저장 폴더:", font=('맑은 고딕', 11, 'bold'),
               fg=COLORS['text_dark'], bg=COLORS['bg_section']).grid(row=0, column=0, sticky='w', padx=(0, 10))
        
        out_entry = tk.Entry(settings_row2, textvariable=self.out_dir, 
                           font=('맑은 고딕', 12), relief='solid', borderwidth=1)
        out_entry.grid(row=0, column=1, sticky='ew', padx=(0, 10), pady=4)
        
        out_btn = tk.Button(settings_row2, text="📁 선택", command=self._pick_out,
                          font=('맑은 고딕', 10), bg=COLORS['primary'], fg='white',
                          relief='flat', padx=15, pady=5)
        out_btn.grid(row=0, column=2, padx=(0, 10))
        
        # 호버 효과
        out_btn.bind('<Enter>', lambda e: out_btn.configure(bg='#3B7DD8'))
        out_btn.bind('<Leave>', lambda e: out_btn.configure(bg=COLORS['primary']))

        open_out_btn = tk.Button(settings_row2, text="📂 폴더 열기", command=self._open_out_folder,
                               font=('맑은 고딕', 10), bg=COLORS['secondary'], fg='white',
                               relief='flat', padx=15, pady=5)
        open_out_btn.grid(row=0, column=3)
        
        # 호버 효과
        open_out_btn.bind('<Enter>', lambda e: open_out_btn.configure(bg='#6B58D3'))
        open_out_btn.bind('<Leave>', lambda e: open_out_btn.configure(bg=COLORS['secondary']))

        # 액션 버튼
        split_action_frame = tk.Frame(split_section, bg=COLORS['bg_section'])
        split_action_frame.pack(fill='x', pady=(10, 0))
        
        reset_btn = tk.Button(split_action_frame, text="🔄 전체 리셋", command=self._reset,
                            font=('맑은 고딕', 11, 'bold'), bg=COLORS['warning'], fg='white',
                            relief='flat', padx=20, pady=8)
        reset_btn.pack(side='right', padx=(10, 0))
        
        # 호버 효과
        reset_btn.bind('<Enter>', lambda e: reset_btn.configure(bg='#FF8C00'))
        reset_btn.bind('<Leave>', lambda e: reset_btn.configure(bg=COLORS['warning']))
        
        batch_btn = tk.Button(split_action_frame, text="⚡ 일괄 분할", command=self._batch,
                            font=('맑은 고딕', 11, 'bold'), bg=COLORS['accent'], fg='white',
                            relief='flat', padx=20, pady=8)
        batch_btn.pack(side='right')
        
        batch_btn.bind('<Enter>', lambda e: e.widget.configure(bg=COLORS['success']))
        batch_btn.bind('<Leave>', lambda e: e.widget.configure(bg=COLORS['accent']))

    def _build_resize_tab(self, parent):
        """크기 조정 탭 구성"""
        resize_section = tk.Frame(parent, bg=COLORS['bg_section'])
        resize_section.pack(fill='both', expand=True, padx=15, pady=15)
        
        # 초기 안내 메시지
        self.resize_guide_frame = tk.Frame(resize_section, bg=COLORS['bg_hover'], relief='solid', borderwidth=1)
        self.resize_guide_frame.pack(fill='x', pady=(0, 15))
        
        self.resize_guide_text = """
        📏 이미지 크기 조정 사용법
        
          1. 📂 찾기 → 이미지 폴더 선택
          2. 📐 목표 가로 크기 입력 (px)
          3. 📏 크기 조정 → 비율 유지하며 일괄 처리
        
          💡 지원 형식: JPG, PNG, WebP, PSD, PSB 등
        """
        
        self.resize_guide_label = tk.Label(self.resize_guide_frame, text=self.resize_guide_text, 
                                font=('맑은 고딕', 10),
                                fg=COLORS['text_medium'], bg=COLORS['bg_hover'],
                                justify='left', padx=20, pady=15)
        self.resize_guide_label.pack()
        
        # 입력 영역
        resize_input_frame = tk.Frame(resize_section, bg=COLORS['bg_section'])
        resize_input_frame.pack(fill='x', pady=(0, 15))
        
        # 폴더 선택
        resize_dir_frame = tk.Frame(resize_input_frame, bg=COLORS['bg_section'])
        resize_dir_frame.pack(fill='x', pady=(0, 15))
        resize_dir_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(resize_dir_frame, text="폴더 선택:", font=('맑은 고딕', 10, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).grid(row=0, column=0, padx=(0, 10))
        
        resize_dir_entry = tk.Entry(resize_dir_frame, textvariable=self.resize_dir,
                                 font=('맑은 고딕', 12), relief='solid', borderwidth=1)
        resize_dir_entry.grid(row=0, column=1, sticky='ew', padx=(0, 10), pady=4)
        
        resize_find_btn = tk.Button(resize_dir_frame, text="📂 찾기", command=self._pick_resize_dir,
                font=('맑은 고딕', 10), bg=COLORS['primary'], fg='white',
                relief='flat', padx=15, pady=5)
        resize_find_btn.grid(row=0, column=2, padx=(0, 10))
        
        # 호버 효과
        resize_find_btn.bind('<Enter>', lambda e: resize_find_btn.configure(bg='#3B7DD8'))
        resize_find_btn.bind('<Leave>', lambda e: resize_find_btn.configure(bg=COLORS['primary']))
        
        # 툴팁 추가
        ToolTip(resize_find_btn, "크기를 조정할 이미지들이 있는 폴더를 선택합니다.")
        
        resize_list_btn = tk.Button(resize_dir_frame, text="📄 파일 목록", command=self._show_resize_files,
                font=('맑은 고딕', 10), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=15, pady=5)
        resize_list_btn.grid(row=0, column=3)
        
        # 호버 효과
        resize_list_btn.bind('<Enter>', lambda e: resize_list_btn.configure(bg='#6B58D3'))
        resize_list_btn.bind('<Leave>', lambda e: resize_list_btn.configure(bg=COLORS['secondary']))
        
        # 툴팁 추가
        ToolTip(resize_list_btn, "파일 목록을 확인하고 제외할 파일을 선택할 수 있습니다.")
        
        # 설정 영역
        resize_settings_frame = tk.LabelFrame(resize_input_frame, text=" 크기 조정 설정 ", 
                                              font=('맑은 고딕', 10, 'bold'), fg=COLORS['text_dark'],
                                              bg=COLORS['bg_section'], relief='solid', borderwidth=1)
        resize_settings_frame.pack(fill='x', pady=(15, 0))
        resize_settings_frame.configure(padx=15, pady=10)
        
        # 첫 번째 행: 목표 크기
        size_row = tk.Frame(resize_settings_frame, bg=COLORS['bg_section'])
        size_row.pack(fill='x', pady=(0, 8))
        
        tk.Label(size_row, text="목표 가로 크기:", font=('맑은 고딕', 11, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).pack(side='left', padx=(0, 10))
        
        width_entry = tk.Entry(size_row, textvariable=self.target_width,
                              font=('맑은 고딕', 12), relief='solid', borderwidth=1, 
                              width=8)
        width_entry.pack(side='left', padx=(0, 5))
        
        tk.Label(size_row, text="px", font=('맑은 고딕', 11, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).pack(side='left')
        
        # 두 번째 행: 리샘플링 품질
        quality_row = tk.Frame(resize_settings_frame, bg=COLORS['bg_section'])
        quality_row.pack(fill='x', pady=(8, 0))
        
        tk.Label(quality_row, text="리샘플링 품질:", font=('맑은 고딕', 11, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).pack(side='left', padx=(0, 10))
        
        quality_values = ['고품질 (느림)', '표준', '빠름']
        quality_menu = ttk.OptionMenu(quality_row, self.resize_quality, self.resize_quality.get(), *quality_values)
        quality_menu.pack(side='left')
        
        # 저장 설정 영역
        save_settings_frame = tk.LabelFrame(resize_input_frame, text=" 저장 설정 ", 
                                           font=('맑은 고딕', 10, 'bold'), fg=COLORS['text_dark'],
                                           bg=COLORS['bg_section'], relief='solid', borderwidth=1)
        save_settings_frame.pack(fill='x', pady=(15, 0))
        save_settings_frame.configure(padx=15, pady=10)
        
        # 첫 번째 행: 저장 옵션들
        options_row = tk.Frame(save_settings_frame, bg=COLORS['bg_section'])
        options_row.pack(fill='x', pady=(0, 8))
        
        # PNG 저장 체크박스
        resize_png_check = tk.Checkbutton(options_row, text="PNG로 저장 (무손실, 큰 파일크기)", 
                                        variable=self.save_as_png,
                                        font=('맑은 고딕', 10), fg=COLORS['text_dark'], 
                                        bg=COLORS['bg_section'],
                                        selectcolor=COLORS['bg_section'])
        resize_png_check.pack(side='left', padx=(0, 20))
        
        # 품질 설정
        tk.Label(options_row, text="품질:", font=('맑은 고딕', 10, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).pack(side='left', padx=(0, 5))
        
        quality_values = ['무손실', 'High', 'Medium', 'Low']
        quality_menu = ttk.OptionMenu(options_row, self.quality, self.quality.get(), *quality_values)
        quality_menu.pack(side='left')
        
        # 두 번째 행: 파일명 옵션
        filename_row = tk.Frame(save_settings_frame, bg=COLORS['bg_section'])
        filename_row.pack(fill='x', pady=(8, 0))
        
        # 크기 접미사 추가 체크박스
        suffix_check = tk.Checkbutton(filename_row, text="파일명에 크기 접미사 추가 (예: _800px)", 
                                     variable=self.add_suffix,
                                     font=('맑은 고딕', 10), fg=COLORS['text_dark'], 
                                     bg=COLORS['bg_section'],
                                     selectcolor=COLORS['bg_section'])
        suffix_check.pack(side='left')
        
        # 상태 표시
        status_frame = tk.Frame(resize_section, bg=COLORS['bg_section'])
        status_frame.pack(fill='x', pady=(0, 15))
        
        self.resize_status_label = tk.Label(status_frame, textvariable=self.resize_status,
                                         font=('맑은 고딕', 10),
                                         fg=COLORS['text_medium'], bg=COLORS['bg_section'])
        self.resize_status_label.pack(anchor='w')
        
        # 액션 버튼
        action_frame = tk.Frame(resize_section, bg=COLORS['bg_section'])
        action_frame.pack(fill='x')
        
        # 크기 조정 버튼
        resize_btn = tk.Button(action_frame, text="📏 크기 조정", 
                            command=self._resize_images,
                            font=('맑은 고딕', 11), bg=COLORS['primary'], fg='white',
                            relief='flat', padx=20, pady=8, state='disabled')
        resize_btn.pack(side='left')
        self.resize_btn = resize_btn
        
        # 호버 효과
        def hover_resize(e):
            if resize_btn['state'] != 'disabled':
                resize_btn.configure(bg='#3B7DD8')
        def leave_resize(e):
            if resize_btn['state'] != 'disabled':
                resize_btn.configure(bg=COLORS['primary'])
        
        resize_btn.bind('<Enter>', hover_resize)
        resize_btn.bind('<Leave>', leave_resize)
        
        # 결과 폴더 열기
        open_resize_btn = tk.Button(action_frame, text="📂 결과 폴더 열기", 
                                 command=lambda: open_folder(Path(self.out_dir.get())),
                                 font=('맑은 고딕', 11), bg=COLORS['primary'], fg='white',
                                 relief='flat', padx=20, pady=8)
        open_resize_btn.pack(side='right')
        
        # 호버 효과
        open_resize_btn.bind('<Enter>', lambda e: open_resize_btn.configure(bg='#3B7DD8'))
        open_resize_btn.bind('<Leave>', lambda e: open_resize_btn.configure(bg=COLORS['primary']))
        
        # 크기 제한 가이드
        limit_frame = tk.Frame(resize_section, bg=COLORS['bg_hover'], 
                             relief='solid', borderwidth=1)
        limit_frame.pack(fill='x', pady=(15, 0))
        
        limit_text = (
            "💡 크기 조정 가이드\n"
            "• 크기 범위: 100px ~ 5,000px\n"
            "• 비율 자동 유지, 원본 파일 보존\n"
            "• 확대 시 화질 저하 가능성 있음"
        )
        
        tk.Label(limit_frame, text=limit_text,
               font=('맑은 고딕', 9), fg=COLORS['text_medium'],
               bg=COLORS['bg_hover'], justify='left',
               padx=15, pady=10).pack()

    def _build_merge_tab(self, parent):
        """합치기 탭 구성"""
        merge_section = tk.Frame(parent, bg=COLORS['bg_section'])
        merge_section.pack(fill='both', expand=True, padx=15, pady=15)
        
        # 초기 안내 메시지
        self.merge_guide_frame = tk.Frame(merge_section, bg=COLORS['bg_hover'], relief='solid', borderwidth=1)
        self.merge_guide_frame.pack(fill='x', pady=(0, 15))
        
        self.merge_guide_text = """
        📌 이미지 합치기 사용법
        
          1. 📂 찾기 버튼을 클릭하여 이미지들이 있는 폴더를 선택하세요
          2. 📄 파일 목록 버튼을 클릭하여 파일들을 확인하고 순서를 조정하세요
          3. 🎯 자동생성 버튼으로 파일명을 생성하거나 직접 입력하세요
          4. 🔄 합치기 버튼을 클릭하여 이미지들을 합치세요
        
          💡 팁: 
          - 여러 이미지를 세로로 합칩니다
          - 이미지는 자동으로 중앙 정렬됩니다
          - 순서는 파일명 순으로 정렬되지만 파일 목록에서 변경 가능합니다
          - 지원 파일 형식: JPG, PNG, WebP, PSD, PSB 등
        """
        
        self.merge_guide_label = tk.Label(self.merge_guide_frame, text=self.merge_guide_text, 
                                font=('맑은 고딕', 10),
                                fg=COLORS['text_medium'], bg=COLORS['bg_hover'],
                                justify='left', padx=20, pady=15)
        self.merge_guide_label.pack()
        
        # 입력 영역
        merge_input_frame = tk.Frame(merge_section, bg=COLORS['bg_section'])
        merge_input_frame.pack(fill='x', pady=(0, 15))
        
        # 폴더 선택
        merge_dir_frame = tk.Frame(merge_input_frame, bg=COLORS['bg_section'])
        merge_dir_frame.pack(fill='x')
        merge_dir_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(merge_dir_frame, text="폴더 선택:", font=('맑은 고딕', 10, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).grid(row=0, column=0, padx=(0, 10))
        
        merge_dir_entry = tk.Entry(merge_dir_frame, textvariable=self.merge_dir,
                                 font=('맑은 고딕', 12), relief='solid', borderwidth=1)
        merge_dir_entry.grid(row=0, column=1, sticky='ew', padx=(0, 10), pady=4)
        
        merge_find_btn = tk.Button(merge_dir_frame, text="📂 찾기", command=self._pick_merge_dir,
                font=('맑은 고딕', 10), bg=COLORS['primary'], fg='white',
                relief='flat', padx=15, pady=5)
        merge_find_btn.grid(row=0, column=2, padx=(0, 10))
        
        # 호버 효과
        merge_find_btn.bind('<Enter>', lambda e: merge_find_btn.configure(bg='#3B7DD8'))
        merge_find_btn.bind('<Leave>', lambda e: merge_find_btn.configure(bg=COLORS['primary']))
        
        # 툴팁 추가
        ToolTip(merge_find_btn, "합칠 이미지들이 있는 폴더를 선택합니다. 폴더 내의 이미지들을 자동으로 검색합니다.")
        
        merge_list_btn = tk.Button(merge_dir_frame, text="📄 파일 목록", command=self._show_merge_files,
                font=('맑은 고딕', 10), bg=COLORS['secondary'], fg='white',
                relief='flat', padx=15, pady=5)
        merge_list_btn.grid(row=0, column=3)
        
        # 호버 효과
        merge_list_btn.bind('<Enter>', lambda e: merge_list_btn.configure(bg='#6B58D3'))
        merge_list_btn.bind('<Leave>', lambda e: merge_list_btn.configure(bg=COLORS['secondary']))
        
        # 툴팁 추가
        ToolTip(merge_list_btn, "파일 목록을 확인하고 순서를 변경할 수 있습니다. 제외할 파일도 선택할 수 있습니다.")
        
        # 파일명 및 저장 옵션 설정
        filename_settings_frame = tk.LabelFrame(merge_input_frame, text=" 저장 설정 ", 
                                              font=('맑은 고딕', 10, 'bold'), fg=COLORS['text_dark'],
                                              bg=COLORS['bg_section'], relief='solid', borderwidth=1)
        filename_settings_frame.pack(fill='x', pady=(15, 0))
        filename_settings_frame.configure(padx=15, pady=10)
        
        # 첫 번째 행: 파일명
        filename_row1 = tk.Frame(filename_settings_frame, bg=COLORS['bg_section'])
        filename_row1.pack(fill='x', pady=(0, 8))
        filename_row1.grid_columnconfigure(1, weight=1)
        
        tk.Label(filename_row1, text="파일명:", font=('맑은 고딕', 11, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).grid(row=0, column=0, padx=(0, 10), sticky='w')
        
        filename_entry = tk.Entry(filename_row1, textvariable=self.merge_filename,
                                font=('맑은 고딕', 12), relief='solid', borderwidth=1, 
                                width=40)  # 더 큰 입력 필드
        filename_entry.grid(row=0, column=1, sticky='ew', padx=(0, 10), pady=4)
        
        # 확장자 표시 (더 크게)
        self.ext_label = tk.Label(filename_row1, text=".jpg", 
                                font=('맑은 고딕', 11, 'bold'),
                                fg=COLORS['primary'], bg=COLORS['bg_section'],
                                width=6)
        self.ext_label.grid(row=0, column=2, padx=(0, 10))
        
        # 자동생성 버튼 (더 크게)
        auto_name_btn = tk.Button(filename_row1, text="🎯 자동생성", 
                                command=self._generate_filename,
                                font=('맑은 고딕', 10), bg=COLORS['accent'], fg='white',
                                relief='flat', padx=15, pady=6)
        auto_name_btn.grid(row=0, column=3)
        
        # 호버 효과
        auto_name_btn.bind('<Enter>', lambda e: auto_name_btn.configure(bg=COLORS['success']))
        auto_name_btn.bind('<Leave>', lambda e: auto_name_btn.configure(bg=COLORS['accent']))
        
        # 두 번째 행: 저장 옵션들
        options_row = tk.Frame(filename_settings_frame, bg=COLORS['bg_section'])
        options_row.pack(fill='x', pady=(8, 0))
        
        # PNG 저장 체크박스
        merge_png_check = tk.Checkbutton(options_row, text="PNG로 저장 (무손실, 큰 파일크기)", 
                                       variable=self.save_as_png,
                                       font=('맑은 고딕', 10), fg=COLORS['text_dark'], 
                                       bg=COLORS['bg_section'],
                                       selectcolor=COLORS['bg_section'])
        merge_png_check.pack(side='left', padx=(0, 20))
        
        # 품질 설정
        tk.Label(options_row, text="품질:", font=('맑은 고딕', 10, 'bold'),
                fg=COLORS['text_dark'], bg=COLORS['bg_section']).pack(side='left', padx=(0, 5))
        
        quality_values = ['무손실', 'High', 'Medium', 'Low']
        quality_menu = ttk.OptionMenu(options_row, self.quality, self.quality.get(), *quality_values)
        quality_menu.pack(side='left')
        
        # PNG 체크박스 변경 시 확장자 업데이트
        self.save_as_png.trace('w', self._update_extension_label)
        self.save_as_png.trace('w', self._update_all_filename_examples)
        
        # 상태 표시
        status_frame = tk.Frame(merge_section, bg=COLORS['bg_section'])
        status_frame.pack(fill='x', pady=(0, 15))
        
        self.merge_status_label = tk.Label(status_frame, textvariable=self.merge_status,
                                         font=('맑은 고딕', 10),
                                         fg=COLORS['text_medium'], bg=COLORS['bg_section'])
        self.merge_status_label.pack(anchor='w')
        
        # 액션 버튼
        action_frame = tk.Frame(merge_section, bg=COLORS['bg_section'])
        action_frame.pack(fill='x')
        
        # 미리보기 버튼
        preview_btn = tk.Button(action_frame, text="👁️ 미리보기", 
                              command=self._preview_merge,
                              font=('맑은 고딕', 11), bg=COLORS['secondary'], fg='white',
                              relief='flat', padx=20, pady=8, state='disabled')
        preview_btn.pack(side='left', padx=(0, 10))
        self.merge_preview_btn = preview_btn
        
        # 호버 효과
        def hover_preview(e):
            if preview_btn['state'] != 'disabled':
                preview_btn.configure(bg='#6B58D3')
        def leave_preview(e):
            if preview_btn['state'] != 'disabled':
                preview_btn.configure(bg=COLORS['secondary'])
        
        preview_btn.bind('<Enter>', hover_preview)
        preview_btn.bind('<Leave>', leave_preview)
        
        # 합치기 버튼
        merge_btn = tk.Button(action_frame, text="🔄 합치기", 
                            command=lambda: self._merge_images(),
                            font=('맑은 고딕', 11), bg=COLORS['primary'], fg='white',
                            relief='flat', padx=20, pady=8, state='disabled')
        merge_btn.pack(side='left')
        self.merge_btn = merge_btn
        
        # 호버 효과
        def hover_merge(e):
            if merge_btn['state'] != 'disabled':
                merge_btn.configure(bg='#3B7DD8')
        def leave_merge(e):
            if merge_btn['state'] != 'disabled':
                merge_btn.configure(bg=COLORS['primary'])
        
        merge_btn.bind('<Enter>', hover_merge)
        merge_btn.bind('<Leave>', leave_merge)
        
        # 결과 폴더 열기
        open_merge_btn = tk.Button(action_frame, text="📂 결과 폴더 열기", 
                                 command=lambda: open_folder(Path(self.out_dir.get())),
                                 font=('맑은 고딕', 11), bg=COLORS['primary'], fg='white',
                                 relief='flat', padx=20, pady=8)
        open_merge_btn.pack(side='right')
        
        # 호버 효과
        open_merge_btn.bind('<Enter>', lambda e: open_merge_btn.configure(bg='#3B7DD8'))
        open_merge_btn.bind('<Leave>', lambda e: open_merge_btn.configure(bg=COLORS['primary']))
        
        # 크기 제한 가이드
        limit_frame = tk.Frame(merge_section, bg=COLORS['bg_hover'], 
                             relief='solid', borderwidth=1)
        limit_frame.pack(fill='x', pady=(15, 0))
        
        limit_text = (
            "⚠️ 이미지 크기 제한\n"
            "• 최대 가로: 10,000px\n"
            "• 최대 총 픽셀: 약 21억 픽셀\n"
            "• PC 메모리에 따라 자동 조정됩니다"
        )
        
        tk.Label(limit_frame, text=limit_text,
               font=('맑은 고딕', 9), fg=COLORS['text_medium'],
               bg=COLORS['bg_hover'], justify='left',
               padx=15, pady=10).pack()



    def _logo(self):
        """로고 표시"""
        p = BASE_DIR / LOGO
        if p.exists():
            try:
                img = Image.open(p)
                img.thumbnail((120, 120))
                self.logo = ImageTk.PhotoImage(img)
                logo_label = tk.Label(self, image=self.logo, bg=COLORS['bg_main'])
                logo_label.place(relx=1.0, rely=1.0, anchor='se', x=-20, y=-40)
            except Exception:
                pass

    def ensure_out(self) -> Path:
        """출력 폴더 확인 및 생성"""
        p = Path(self.out_dir.get())
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ensure_merge_out(self) -> Path:
        """합치기 전용 출력 폴더 확인 및 생성"""
        base_out = Path(self.out_dir.get())
        merge_out = base_out / "merged"
        merge_out.mkdir(parents=True, exist_ok=True)
        return merge_out

    def ensure_resize_out(self) -> Path:
        """크기 조정 전용 출력 폴더 확인 및 생성"""
        base_out = Path(self.out_dir.get())
        resize_out = base_out / "resized"
        resize_out.mkdir(parents=True, exist_ok=True)
        return resize_out



    def _update_file_rows(self):
        """파일 목록 업데이트"""
        if not self.in_dir.get():
            return
            
        directory = Path(self.in_dir.get())
        try:
            files = []
            for ext in SUPPORTED:
                files.extend(directory.glob(f"*{ext}"))
                files.extend(directory.glob(f"*{ext.upper()}"))
            
            files = sorted(set(files), key=lambda x: x.name.lower())
            
            # 제외되지 않은 파일만
            included_files = [f for f in files if f.name not in self.split_file_viewer.excluded_files]
            
            # 안내 메시지 숨기기 (파일이 있을 때)
            if hasattr(self, 'guide_label') and included_files:
                self.guide_label.destroy()
                delattr(self, 'guide_label')
            
            # 현재 행 수와 필요한 행 수 비교
            needed_rows = len(included_files)
            current_rows = len(self.rows)
            
            if needed_rows > current_rows:
                # 부족한 행 추가
                for _ in range(needed_rows - current_rows):
                    self._add_file_row()
            elif needed_rows < current_rows:
                # 초과하는 행 삭제
                for _ in range(current_rows - needed_rows):
                    if self.rows:
                        row_to_remove = self.rows.pop()
                        row_to_remove.destroy()
            
            # 남은 행에 파일 설정
            for i, r in enumerate(self.rows):
                if i < len(included_files):
                    r.set_file(included_files[i].name, included_files[i])
                else:
                    r.clear()
                    
        except Exception as e:
            messagebox.showerror("오류", f"파일 로드 실패: {e}")

    def _show_split_files(self):
        """분할 파일 목록 표시"""
        directory = Path(self.in_dir.get()) if self.in_dir.get() else None
        if not directory or not directory.exists():
            messagebox.showwarning("경고", "먼저 입력 폴더를 선택해주세요.")
            return
        self.split_file_viewer.show(directory, SUPPORTED)

    def _show_merge_files(self):
        """합칠 파일 목록 표시"""
        directory = Path(self.merge_dir.get()) if self.merge_dir.get() else None
        if not directory or not directory.exists():
            messagebox.showwarning("경고", "먼저 합칠 폴더를 선택해주세요.")
            return
        self.merge_file_viewer.show(directory, SUPPORTED)

    def _show_resize_files(self):
        """크기 조정할 파일 목록 표시"""
        directory = Path(self.resize_dir.get()) if self.resize_dir.get() else None
        if not directory or not directory.exists():
            messagebox.showwarning("경고", "먼저 크기 조정할 폴더를 선택해주세요.")
            return
        self.resize_file_viewer.show(directory, SUPPORTED)

    def _open_out_folder(self):
        """출력 폴더 열기"""
        out_path = Path(self.out_dir.get())
        if out_path.exists():
            open_folder(out_path)
        else:
            if messagebox.askyesno("폴더 없음", 
                                 f"저장 폴더가 존재하지 않습니다.\n"
                                 f"폴더를 생성하고 열까요?\n\n{out_path}"):
                try:
                    out_path.mkdir(parents=True, exist_ok=True)
                    open_folder(out_path)
                except Exception as e:
                    messagebox.showerror("오류", f"폴더 생성 실패: {e}")

    def _pick_in(self):
        """입력 폴더 선택"""
        d = filedialog.askdirectory(title="이미지가 있는 폴더를 선택하세요")
        if not d:
            return
        self.in_dir.set(d)
        # 안내 메시지 숨기기
        if hasattr(self, 'guide_label'):
            self.guide_label.pack_forget()
        self._load_files_from_dir(Path(d))

    def _pick_out(self):
        """출력 폴더 선택"""
        d = filedialog.askdirectory(title="분할된 이미지를 저장할 폴더를 선택하세요")
        if d:
            self.out_dir.set(d)

    def _pick_merge_dir(self):
        """합칠 폴더 선택"""
        d = filedialog.askdirectory(title="합칠 이미지들이 있는 폴더를 선택하세요")
        if d:
            self.merge_dir.set(d)
            # 안내 메시지 숨기기
            if hasattr(self, 'merge_guide_frame'):
                self.merge_guide_frame.pack_forget()
            self.update_merge_status()

    def _pick_resize_dir(self):
        """크기 조정할 폴더 선택"""
        d = filedialog.askdirectory(title="크기를 조정할 이미지들이 있는 폴더를 선택하세요")
        if d:
            self.resize_dir.set(d)
            # 안내 메시지 숨기기
            if hasattr(self, 'resize_guide_frame'):
                self.resize_guide_frame.pack_forget()
            self.update_resize_status()



    def _on_platform_change(self, event=None):
        """플랫폼 변경"""
        self._update_platform_info()
        
    def _update_platform_info(self):
        """플랫폼 정보 업데이트"""
        platform = self.merge_platform.get()
        if platform in PLATFORM_SPECS:
            spec = PLATFORM_SPECS[platform]
            info = f"최대 {spec['max_width']}×{spec['max_height']}px, "
            info += f"{spec['format'].upper()} {spec['quality']}%"
            self.platform_info_label.config(text=info)

    def update_merge_status(self):
        """합치기 상태 업데이트"""
        merge_path = Path(self.merge_dir.get())
        
        if not merge_path.exists():
            self.merge_status.set("⚠️ 합칠 폴더를 선택해주세요")
            self.merge_btn.configure(state='disabled')
            self.merge_preview_btn.configure(state='disabled')
            return
            
        try:
            # 이미지 파일 찾기
            image_files = []
            for ext in SUPPORTED:
                image_files.extend(merge_path.glob(f"*{ext}"))
                image_files.extend(merge_path.glob(f"*{ext.upper()}"))
            
            image_files = sorted(set(image_files), key=lambda x: x.name.lower())
            
            if not image_files:
                self.merge_status.set("⚠️ 선택한 폴더에 이미지 파일이 없습니다")
                self.merge_btn.configure(state='disabled')
                self.merge_preview_btn.configure(state='disabled')
                return
            
            # 크기 계산
            total_size = sum(f.stat().st_size for f in image_files)
            
            # 예상 크기 계산
            total_height = 0
            max_width = 0
            for f in image_files[:20]:  # 처음 20개만 확인
                info = get_image_info(f)
                if info:
                    total_height += info.height
                    max_width = max(max_width, info.width)
            
            if len(image_files) > 20:
                # 나머지는 평균으로 추정
                avg_height = total_height // 20
                total_height += avg_height * (len(image_files) - 20)
            
            status = f"✓ {len(image_files)}개 파일 준비 완료\n"
            status += f"총 크기: {format_file_size(total_size)} | "
            status += f"예상: {format_image_dimensions(max_width, total_height)}"
            
            self.merge_status.set(status)
            self.merge_btn.configure(state='normal')
            self.merge_preview_btn.configure(state='normal')
            
        except Exception as e:
            self.merge_status.set(f"⚠️ 오류: {str(e)}")
            self.merge_btn.configure(state='disabled')
            self.merge_preview_btn.configure(state='disabled')

    def update_resize_status(self):
        """크기 조정 상태 업데이트"""
        resize_path = Path(self.resize_dir.get())
        
        if not resize_path.exists():
            self.resize_status.set("⚠️ 크기를 조정할 폴더를 선택해주세요")
            self.resize_btn.configure(state='disabled')
            return
            
        # 목표 크기 유효성 검사
        try:
            target_width = int(self.target_width.get())
            if target_width < 100 or target_width > 5000:
                self.resize_status.set("⚠️ 목표 가로 크기는 100px ~ 5,000px 사이여야 합니다")
                self.resize_btn.configure(state='disabled')
                return
        except ValueError:
            self.resize_status.set("⚠️ 올바른 가로 크기를 입력해주세요 (숫자만)")
            self.resize_btn.configure(state='disabled')
            return
            
        try:
            # 이미지 파일 찾기
            image_files = []
            for ext in SUPPORTED:
                image_files.extend(resize_path.glob(f"*{ext}"))
                image_files.extend(resize_path.glob(f"*{ext.upper()}"))
            
            image_files = sorted(set(image_files), key=lambda x: x.name.lower())
            
            if not image_files:
                self.resize_status.set("⚠️ 선택한 폴더에 이미지 파일이 없습니다")
                self.resize_btn.configure(state='disabled')
                return
            
            # 제외된 파일 필터링
            if hasattr(self.resize_file_viewer, 'excluded_files'):
                image_files = [f for f in image_files if f.name not in self.resize_file_viewer.excluded_files]
            
            if not image_files:
                self.resize_status.set("⚠️ 처리할 이미지가 없습니다 (모든 파일이 제외됨)")
                self.resize_btn.configure(state='disabled')
                return
            
            # 크기 계산
            total_size = sum(f.stat().st_size for f in image_files)
            
            status = f"✓ {len(image_files)}개 파일 준비 완료\n"
            status += f"총 크기: {format_file_size(total_size)} | "
            status += f"목표 가로: {target_width}px"
            
            self.resize_status.set(status)
            self.resize_btn.configure(state='normal')
            
        except Exception as e:
            self.resize_status.set(f"⚠️ 오류: {str(e)}")
            self.resize_btn.configure(state='disabled')

    def _preview_merge(self):
        """합치기 미리보기"""
        merge_path = Path(self.merge_dir.get())
        if not merge_path.exists():
            return
            
        # 이미지 파일 찾기
        image_files = []
        for ext in SUPPORTED:
            image_files.extend(merge_path.glob(f"*{ext}"))
            image_files.extend(merge_path.glob(f"*{ext.upper()}"))
        
        image_files = sorted(set(image_files), key=lambda x: x.name.lower())
        
        if not image_files:
            return
            
        # 제외된 파일 필터링
        if hasattr(self.merge_file_viewer, 'excluded_files'):
            image_files = [f for f in image_files if f.name not in self.merge_file_viewer.excluded_files]
            
        if not image_files:
            messagebox.showwarning("알림", "처리할 이미지가 없습니다.\n제외되지 않은 이미지를 선택해주세요.")
            return
            
        # 미리보기 다이얼로그
        preview_dialog = MergePreviewDialog(self, image_files)
        self.wait_window(preview_dialog)
        
        if preview_dialog.result:
            # 순서가 조정된 파일 목록으로 합치기 실행
            self._merge_images(preview_dialog.result)

    def _merge_images(self, files=None):
        """이미지 합치기"""
        if files is None:
            # 파일 목록 가져오기
            merge_path = Path(self.merge_dir.get())
            if not merge_path.exists():
                messagebox.showerror("오류", "합칠 폴더를 선택해주세요.")
                return
                
            image_files = []
            for ext in SUPPORTED:
                image_files.extend(merge_path.glob(f"*{ext}"))
                image_files.extend(merge_path.glob(f"*{ext.upper()}"))
            
            files = sorted(set(image_files), key=lambda x: x.name.lower())
        
        if not files:
            messagebox.showerror("오류", "이미지 파일을 찾을 수 없습니다.")
            return
        
        # 제외된 파일 필터링
        if hasattr(self.merge_file_viewer, 'excluded_files'):
            files = [f for f in files if f.name not in self.merge_file_viewer.excluded_files]
        
        if not files:
            messagebox.showwarning("알림", "처리할 이미지가 없습니다.")
            return
        
        # 출력 설정
        base_filename = self.merge_filename.get().strip()
        
        # 파일명이 비어있거나 기본값이면 자동 생성
        if not base_filename or base_filename == "merged_images":
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"merged_{len(files)}images_{timestamp}"
        
        # 파일명 유효성 검사 및 정리
        base_filename = self._clean_filename(base_filename)
        
        if self.save_as_png.get():
            output_name = f"{base_filename}.png"
        else:
            output_name = f"{base_filename}.jpg"
            
        output_path = self.ensure_merge_out() / output_name
        
        # 중복 파일명 처리
        if output_path.exists():
            base_name = output_path.stem
            extension = output_path.suffix
            counter = 1
            while output_path.exists():
                new_name = f"{base_name}_{counter:03d}{extension}"
                output_path = self.ensure_merge_out() / new_name
                counter += 1
        
        # 합치기 작업
        task = MergeTask(
            files=files,
            output_path=output_path,
            quality=self.quality.get(),
            platform=None,
            save_as_png=self.save_as_png.get()
        )
        
        # 진행률 다이얼로그
        progress_dialog = ProgressDialog(self, "이미지 합치기", 
                                       f"{len(files)}개 이미지 처리 중...")
        
        def progress_callback(value):
            progress_dialog.update_progress(value)
            if value >= 50:
                progress_dialog.update_message(f"이미지 합치기 중... ({int(value)}%)")
        
        def merge_task():
            try:
                merge_images_advanced(task, progress_callback, progress_dialog.cancel_event)
                
                if not progress_dialog.cancel_event.is_set():
                    self.after(0, lambda: messagebox.showinfo("완료", 
                        f"이미지 합치기가 완료되었습니다!\n\n"
                        f"파일명: {output_name}\n"
                        f"위치: {output_path.parent}"))
                    
                self.after(0, progress_dialog.destroy)
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("실패", 
                    f"이미지 합치기 실패:\n{str(e)}"))
                self.after(0, progress_dialog.destroy)
        
        # 스레드 실행
        thread = threading.Thread(target=merge_task)
        thread.daemon = True
        thread.start()

    def _resize_images(self):
        """이미지 크기 조정"""
        resize_path = Path(self.resize_dir.get())
        if not resize_path.exists():
            messagebox.showerror("오류", "크기 조정할 폴더를 선택해주세요.")
            return
            
        # 목표 크기 검증
        try:
            target_width = int(self.target_width.get())
            if target_width < 100 or target_width > 5000:
                messagebox.showerror("오류", "목표 가로 크기는 100px ~ 5,000px 사이여야 합니다.")
                return
        except ValueError:
            messagebox.showerror("오류", "올바른 가로 크기를 입력해주세요.")
            return
            
        # 파일 목록 가져오기
        image_files = []
        for ext in SUPPORTED:
            image_files.extend(resize_path.glob(f"*{ext}"))
            image_files.extend(resize_path.glob(f"*{ext.upper()}"))
        
        files = sorted(set(image_files), key=lambda x: x.name.lower())
        
        if not files:
            messagebox.showerror("오류", "이미지 파일을 찾을 수 없습니다.")
            return
        
        # 제외된 파일 필터링
        if hasattr(self.resize_file_viewer, 'excluded_files'):
            files = [f for f in files if f.name not in self.resize_file_viewer.excluded_files]
        
        if not files:
            messagebox.showwarning("알림", "처리할 이미지가 없습니다.")
            return
        
        # 리샘플링 알고리즘 선택
        quality = self.resize_quality.get()
        if quality == "고품질 (느림)":
            resample = Image.LANCZOS
        elif quality == "표준":
            resample = Image.BICUBIC
        else:  # 빠름
            resample = Image.BILINEAR
        
        # 진행률 다이얼로그
        progress_dialog = ProgressDialog(self, "이미지 크기 조정", 
                                       f"{len(files)}개 이미지 크기 조정 중...")
        
        def progress_callback(value):
            progress_dialog.update_progress(value)
        
        def resize_task():
            try:
                output_dir = self.ensure_resize_out()
                processed = 0
                failed = 0
                
                for i, file_path in enumerate(files):
                    if progress_dialog.cancel_event.is_set():
                        break
                        
                    try:
                        # 이미지 로드
                        if file_path.suffix.lower() in ['.psd', '.psb']:
                            img = load_psd_image(file_path)
                        else:
                            img = Image.open(file_path)
                        
                        if img is None:
                            failed += 1
                            continue
                        
                        # RGBA 이미지는 RGB로 변환
                        if img.mode == 'RGBA':
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            background.paste(img, mask=img.split()[-1])
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        # 현재 크기
                        original_width, original_height = img.size
                        
                        # 새로운 크기 계산 (비율 유지)
                        if original_width == target_width:
                            # 이미 목표 크기면 건너뛰기
                            processed += 1
                            continue
                            
                        ratio = target_width / original_width
                        new_height = int(original_height * ratio)
                        
                        # 크기 조정
                        resized_img = img.resize((target_width, new_height), resample)
                        
                        # DPI 정보 보존 (웹툰 표준 300 DPI로 설정)
                        if hasattr(img, 'info') and 'dpi' in img.info:
                            # 원본 DPI 유지
                            dpi = img.info['dpi']
                        else:
                            # 기본 DPI 300으로 설정 (웹툰/인쇄 표준)
                            dpi = (300, 300)
                        
                        # 출력 파일명 생성
                        base_name = file_path.stem
                        if self.add_suffix.get():
                            output_name = f"{base_name}_{target_width}px{file_path.suffix}"
                        else:
                            output_name = f"{base_name}{file_path.suffix}"
                        
                        output_path = output_dir / output_name
                        
                        # 중복 파일명 처리
                        counter = 1
                        while output_path.exists():
                            if self.add_suffix.get():
                                output_name = f"{base_name}_{target_width}px_{counter:03d}{file_path.suffix}"
                            else:
                                output_name = f"{base_name}_{counter:03d}{file_path.suffix}"
                            output_path = output_dir / output_name
                            counter += 1
                        
                        # 저장 (DPI 정보 포함)
                        save_image_with_quality(resized_img, output_path, self.quality.get(), 
                                              self.save_as_png.get(), dpi=dpi)
                        
                        processed += 1
                        
                    except Exception as e:
                        print(f"파일 처리 실패 {file_path}: {e}")
                        failed += 1
                    
                    # 진행률 업데이트
                    progress = ((i + 1) / len(files)) * 100
                    self.after(0, lambda p=progress: progress_callback(p))
                
                if not progress_dialog.cancel_event.is_set():
                    self.after(0, lambda: messagebox.showinfo("완료", 
                        f"이미지 크기 조정이 완료되었습니다!\n\n"
                        f"처리 완료: {processed}개\n"
                        f"실패: {failed}개\n"
                        f"목표 크기: {target_width}px\n"
                        f"저장 위치: {output_dir}"))
                    
                self.after(0, progress_dialog.destroy)
                
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("실패", 
                    f"이미지 크기 조정 실패:\n{str(e)}"))
                self.after(0, progress_dialog.destroy)
        
        # 스레드 실행
        thread = threading.Thread(target=resize_task)
        thread.daemon = True
        thread.start()

    def _reset(self):
        """전체 리셋"""
        if messagebox.askyesno("확인", "모든 입력을 초기화하시겠습니까?"):
            self.in_dir.set('')
            self.out_dir.set(str(unique_dir(BASE_OUT)))
            self.merge_dir.set('')
            self.merge_filename.set('')
            self.resize_dir.set('')
            self.target_width.set('800')
            
            # 모든 파일 행 제거
            for r in self.rows:
                r.destroy()
            self.rows.clear()
            
            # 분할 탭 안내 메시지 다시 표시
            if not hasattr(self, 'guide_label'):
                self.guide_label = tk.Label(self.rows_frame, 
                                           text="📌 이미지 분할 사용법\n\n"
                                                "1. 위의 '📁 찾기' 버튼으로 이미지가 있는 폴더를 선택해주세요\n"
                                                "2. 또는 '📄 파일 목록' 버튼으로 개별 파일을 선택/제외할 수 있습니다\n"
                                                "3. 폴더 선택 후 각 이미지별로 분할 설정을 할 수 있습니다\n"
                                                "4. 분할 위치는 '미리보기' 버튼으로 시각적으로 설정 가능합니다\n\n"
                                                "💡 지원 형식: JPG, PNG, WebP, PSD, PSB 등 주요 이미지 파일",
                                           font=('맑은 고딕', 10), fg=COLORS['text_medium'], 
                                           bg=COLORS['bg_section'], justify='left', 
                                           relief='flat', padx=20, pady=40)
                self.guide_label.pack(expand=True, fill='both')
            
            # 합치기 탭 안내 메시지 다시 표시
            if hasattr(self, 'merge_guide_frame'):
                self.merge_guide_frame.pack(fill='x', pady=(0, 15))
                self.merge_guide_label.configure(text=self.merge_guide_text)
            
            # 크기 조정 탭 안내 메시지 다시 표시
            if hasattr(self, 'resize_guide_frame'):
                self.resize_guide_frame.pack(fill='x', pady=(0, 15))
                self.resize_guide_label.configure(text=self.resize_guide_text)
            
            # 상태 관련 초기화
            if hasattr(self, 'merge_btn'):
                self.merge_btn.configure(state='disabled')
            if hasattr(self, 'merge_preview_btn'):
                self.merge_preview_btn.configure(state='disabled')
            if hasattr(self, 'resize_btn'):
                self.resize_btn.configure(state='disabled')
            
            # 상태 메시지 초기화
            self.merge_status.set("")
            self.resize_status.set("")
            
            messagebox.showinfo('리셋 완료', '모든 입력이 초기화되었습니다.')

    def _batch(self):
        """일괄 분할"""
        t = [r for r in self.rows if r.has_input()]
        if not t:
            messagebox.showinfo('알림', '처리할 입력이 없습니다.')
            return
            
        # 진행률 다이얼로그
        progress_dialog = ProgressDialog(self, "일괄 분할", 
                                       f"{len(t)}개 파일 처리 중...")
        
        completed = 0
        
        def process_next(index=0):
            nonlocal completed
            
            if index >= len(t) or progress_dialog.cancel_event.is_set():
                progress_dialog.destroy()
                if completed > 0:
                    messagebox.showinfo('일괄 분할 완료', 
                        f"{completed}/{len(t)} 파일 처리 완료\n\n"
                        f"저장 위치: {self.ensure_out()}")
                return
            
            row = t[index]
            progress_dialog.update_message(f"처리 중: {row.path.name} ({index+1}/{len(t)})")
            progress_dialog.update_progress((index / len(t)) * 100)
            
            # 분할 실행
            original_state = row.state.get()
            row._do_split()
            
            # 결과 확인
            self.after(100, lambda: check_completion(index, original_state))
        
        def check_completion(index, original_state):
            nonlocal completed
            row = t[index]
            
            # 상태가 변경되었는지 확인
            if row.state.get() != original_state:
                if row.state.get() in ['OK', 'SKIP'] or row.state.get().startswith('v'):
                    completed += 1
                # 다음 처리
                self.after(100, lambda: process_next(index + 1))
            else:
                # 아직 처리 중
                self.after(100, lambda: check_completion(index, original_state))
        
        # 처리 시작
        process_next(0)

    def _add_file_row(self):
        """파일 행 추가"""
        idx = len(self.rows)
        row = FileRow(self.rows_frame, idx)
        row.app = self
        self.rows.append(row)
        return row

    def _load_files_from_dir(self, directory: Path):
        """디렉토리에서 파일 로드"""
        try:
            files = []
            for ext in SUPPORTED:
                files.extend(directory.glob(f"*{ext}"))
                files.extend(directory.glob(f"*{ext.upper()}"))
            
            files = sorted(set(files), key=lambda x: x.name.lower())[:20]  # 최대 20개
            
            # 필요한 만큼 행 추가
            while len(self.rows) < len(files):
                self._add_file_row()
            
            for i, r in enumerate(self.rows):
                if i < len(files):
                    r.set_file(files[i].name, files[i])
                else:
                    r.clear()
                    
        except Exception as e:
            messagebox.showerror("오류", f"파일 로드 실패: {e}")



    def _save_settings(self):
        """설정 저장"""
        self.config['quality'] = self.quality.get()
        self.config['save_as_png'] = self.save_as_png.get()
        ConfigManager.save(self.config)
            
    def _generate_filename(self):
        """파일명 자동 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = Path(self.merge_dir.get()).name if self.merge_dir.get() else "images"
        auto_name = f"{folder_name}_{timestamp}"
        self.merge_filename.set(auto_name)
    
    def _update_extension_label(self, *args):
        """확장자 라벨 업데이트"""
        if hasattr(self, 'ext_label'):
            ext = ".png" if self.save_as_png.get() else ".jpg"
            self.ext_label.config(text=ext)
    
    def _update_all_filename_examples(self, *args):
        """모든 파일 행의 파일명 예시 업데이트"""
        if hasattr(self, 'rows'):
            for row in self.rows:
                row._update_filename_example()
    
    def _clean_filename(self, filename):
        """파일명 정리 및 유효성 검사"""
        # 금지된 문자 제거
        forbidden_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
        for char in forbidden_chars:
            filename = filename.replace(char, '_')
        
        # 앞뒤 공백 및 점 제거
        filename = filename.strip(' .')
        
        # 빈 문자열이면 기본값 사용
        if not filename:
            filename = "merged_images"
        
        # 길이 제한 (최대 200자)
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename

    def _on_close(self):
        """창 닫기 처리"""
        # 설정 저장
        self._save_settings()
        
        # 메인 창 종료
        if self.master:
            self.master.quit()
            self.master.destroy()

    def show_context_menu(self, event):
        """우클릭 메뉴"""
        canvas_y = self.canvas.canvasy(event.y)
        scale_factor = self.zoom_ratio / 100.0
        
        # 클릭한 위치 저장
        self.context_click_y = int((canvas_y - self.y_offset) / scale_factor)
        
        # 선 근처 확인
        for i, point in enumerate(self.cut_points):
            display_y = point * scale_factor + self.y_offset
            if abs(canvas_y - display_y) <= 12:
                self.selected_point_idx = i
                self.context_menu.post(event.x_root, event.y_root)
                return
        
        self.selected_point_idx = None
        self.context_menu.post(event.x_root, event.y_root)

# ===== 메인 함수 =====
def _dpi():
    """DPI 설정"""
    if sys.platform == 'win32':
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

def main():
    """메인 함수"""
    _dpi()
    
    # 기본 Tk 창 생성
    root = tk.Tk()
    
    root.title('악어슬라이서 v1.0')
    
    # 창 크기 및 위치 설정
    window_width = 1400
    window_height = 950
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{x}+{y}")
    root.minsize(1400, 850)  # 최소 창 크기 설정
    
    # 아이콘 설정
    try:
        icon_path = BASE_DIR / 'icon.ico'
        if icon_path.exists():
            root.iconbitmap(str(icon_path))
    except:
        pass
    
    # 스타일 설정
    style = ttk.Style()
    style.theme_use('clam')
    
    # 스크롤바 스타일 커스터마이징
    style.element_create('Custom.Scrollbar.trough', 'from', 'default')
    style.element_create('Custom.Scrollbar.thumb', 'from', 'default')
    
    # 수직 스크롤바 레이아웃
    style.layout('Vertical.TScrollbar', 
                [('Custom.Scrollbar.trough', {'sticky': 'ns', 'children':
                    [('Custom.Scrollbar.thumb', {'sticky': 'nsew'})]})])
                    
    # 수평 스크롤바 레이아웃
    style.layout('Horizontal.TScrollbar', 
                [('Custom.Scrollbar.trough', {'sticky': 'ew', 'children':
                    [('Custom.Scrollbar.thumb', {'sticky': 'nsew'})]})])
    
    # 스크롤바 스타일 설정
    style.configure('Vertical.TScrollbar',
                   background='#CCCCCC',  # thumb 색상
                   troughcolor='#F0F0F0', # trough 색상
                   borderwidth=0,
                   relief='flat',
                   width=26)
                   
    style.configure('Horizontal.TScrollbar',
                   background='#CCCCCC',  # thumb 색상
                   troughcolor='#F0F0F0', # trough 색상
                   borderwidth=0,
                   relief='flat',
                   width=26)
                   
    # 마우스 오버/클릭 효과
    style.map('Vertical.TScrollbar',
             background=[('active', '#AAAAAA'),
                        ('pressed', '#999999')])
                        
    style.map('Horizontal.TScrollbar',
             background=[('active', '#AAAAAA'),
                        ('pressed', '#999999')])
    
    app = App(root)
    
    # 메뉴바 추가
    menubar = tk.Menu(root)
    root.config(menu=menubar)
    
    # 도움말 메뉴
    help_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="도움말", menu=help_menu)
    help_menu.add_command(label="업데이트 확인", command=lambda: AutoUpdater(root).check_updates(show_no_update=True))
    help_menu.add_separator()
    help_menu.add_command(label="정보", command=lambda: messagebox.showinfo("정보", f"악어슬라이서 v{CURRENT_VERSION}\n\n이미지 분할/합치기/크기조정 도구"))
    
    # 시작 시 자동 업데이트 확인 (3초 후)
    root.after(3000, lambda: check_for_updates_on_startup(root))
    
    root.mainloop()

# 마우스 휠 이벤트 처리를 위한 함수 추가
def on_mousewheel(event, widget):
    """마우스 휠 이벤트 처리"""
    if event.delta:
        delta = event.delta
    elif event.num == 4:  # Linux에서 위로 스크롤
        delta = 120
    elif event.num == 5:  # Linux에서 아래로 스크롤
        delta = -120
    else:
        return
        
    widget.yview_scroll(int(-1 * (delta / 120)), "units")

# ===== 자동 업데이트 시스템 =====
class AutoUpdater:
    """자동 업데이트 관리 클래스"""
    
    def __init__(self, parent=None):
        self.parent = parent
        self.current_version = CURRENT_VERSION
        
    def check_updates(self, show_no_update=False):
        """업데이트 확인"""
        try:
            # GitHub 우선 확인
            github_version, github_url = self._check_github()
            if github_version and self._is_newer_version(github_version):
                self._show_update_dialog(github_version, github_url, "GitHub")
                return True
                
            # 구글 드라이브 확인 (백업)
            drive_version = self._check_drive()
            if drive_version and self._is_newer_version(drive_version):
                self._show_update_dialog(drive_version, DOWNLOAD_URL, "Google Drive")
                return True
                
            if show_no_update:
                messagebox.showinfo("업데이트", "최신 버전을 사용 중입니다.")
                
        except Exception as e:
            if show_no_update:
                messagebox.showerror("업데이트 확인 실패", f"네트워크 연결을 확인해주세요.\n{str(e)}")
        
        return False
    
    def _check_github(self):
        """GitHub 릴리스 확인"""
        try:
            response = requests.get(GITHUB_API_URL, timeout=10)
            if response.status_code == 200:
                data = response.json()
                version = data['tag_name'].lstrip('v')
                download_url = data['assets'][0]['browser_download_url'] if data['assets'] else None
                return version, download_url
        except:
            pass
        return None, None
    
    def _check_drive(self):
        """구글 드라이브 버전 확인"""
        try:
            response = requests.get(UPDATE_CHECK_URL, timeout=10)
            if response.status_code == 200:
                return response.text.strip()
        except:
            pass
        return None
    
    def _download_from_drive(self, file_id, destination):
        """구글 드라이브에서 파일 다운로드 (큰 파일 지원)"""
        import requests
        
        def get_confirm_token(response):
            for key, value in response.cookies.items():
                if key.startswith('download_warning'):
                    return value
            return None
        
        def save_response_content(response, destination, progress_callback=None):
            CHUNK_SIZE = 32768
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(destination, "wb") as f:
                for chunk in response.iter_content(CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)
        
        URL = "https://docs.google.com/uc?export=download"
        session = requests.Session()
        
        response = session.get(URL, params={'id': file_id}, stream=True)
        token = get_confirm_token(response)
        
        if token:
            params = {'id': file_id, 'confirm': token}
            response = session.get(URL, params=params, stream=True)
        
        return response
    
    def _is_newer_version(self, remote_version):
        """버전 비교"""
        try:
            current_parts = [int(x) for x in self.current_version.split('.')]
            remote_parts = [int(x) for x in remote_version.split('.')]
            
            # 길이 맞추기
            max_len = max(len(current_parts), len(remote_parts))
            current_parts.extend([0] * (max_len - len(current_parts)))
            remote_parts.extend([0] * (max_len - len(remote_parts)))
            
            return remote_parts > current_parts
        except:
            return False
    
    def _show_update_dialog(self, new_version, download_url, source):
        """업데이트 다이얼로그 표시"""
        # 자동 업데이트 옵션 추가
        dialog = tk.Toplevel(self.parent)
        dialog.title("업데이트 알림")
        dialog.geometry("400x250")
        dialog.resizable(False, False)
        dialog.configure(bg='white')
        
        # 모달 설정
        dialog.transient(self.parent)
        dialog.grab_set()
        
        # 중앙 정렬
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (250 // 2)
        dialog.geometry(f"400x250+{x}+{y}")
        
        # 메시지
        message = f"새로운 버전이 있습니다!\n\n현재 버전: {self.current_version}\n최신 버전: {new_version}\n소스: {source}"
        tk.Label(dialog, text=message, font=('맑은 고딕', 11), 
                bg='white', justify='center').pack(pady=20)
        
        # 버튼 프레임
        btn_frame = tk.Frame(dialog, bg='white')
        btn_frame.pack(pady=10)
        
        # 자동 업데이트 버튼
        auto_btn = tk.Button(btn_frame, text="🚀 자동 업데이트", 
                           command=lambda: self._auto_update(dialog, download_url, new_version),
                           font=('맑은 고딕', 10), bg='#4CAF50', fg='white',
                           relief='flat', padx=20, pady=8)
        auto_btn.pack(side='left', padx=5)
        
        # 수동 다운로드 버튼
        manual_btn = tk.Button(btn_frame, text="🌐 수동 다운로드", 
                             command=lambda: self._manual_download(dialog, download_url),
                             font=('맑은 고딕', 10), bg='#2196F3', fg='white',
                             relief='flat', padx=20, pady=8)
        manual_btn.pack(side='left', padx=5)
        
        # 나중에 버튼
        later_btn = tk.Button(btn_frame, text="나중에", 
                            command=dialog.destroy,
                            font=('맑은 고딕', 10), bg='#757575', fg='white',
                            relief='flat', padx=20, pady=8)
        later_btn.pack(side='left', padx=5)
    
    def _auto_update(self, dialog, download_url, new_version):
        """자동 업데이트 실행"""
        dialog.destroy()
        
        # 진행률 다이얼로그
        progress_dialog = tk.Toplevel(self.parent)
        progress_dialog.title("자동 업데이트")
        progress_dialog.geometry("400x150")
        progress_dialog.resizable(False, False)
        progress_dialog.configure(bg='white')
        progress_dialog.transient(self.parent)
        progress_dialog.grab_set()
        
        # 중앙 정렬
        progress_dialog.update_idletasks()
        x = (progress_dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (progress_dialog.winfo_screenheight() // 2) - (150 // 2)
        progress_dialog.geometry(f"400x150+{x}+{y}")
        
        status_label = tk.Label(progress_dialog, text="업데이트를 다운로드 중...", 
                              font=('맑은 고딕', 11), bg='white')
        status_label.pack(pady=20)
        
        progress_var = tk.DoubleVar()
        progress_bar = ttk.Progressbar(progress_dialog, variable=progress_var,
                                     length=350, mode='determinate')
        progress_bar.pack(pady=10)
        
        def download_and_install():
            try:
                import urllib.request
                import tempfile
                import subprocess
                import os
                
                # 임시 파일 경로
                temp_dir = tempfile.gettempdir()
                temp_file = os.path.join(temp_dir, f"akeo_slicer_v{new_version}.exe")
                
                def progress_hook(block_num, block_size, total_size):
                    if total_size > 0:
                        percent = min(100, (block_num * block_size * 100) / total_size)
                        progress_var.set(percent)
                        progress_dialog.update()
                
                # 다운로드 (구글 드라이브 vs GitHub 구분)
                status_label.config(text="업데이트를 다운로드 중...")
                
                if "drive.google.com" in download_url:
                    # 구글 드라이브 다운로드
                    file_id = download_url.split('id=')[1].split('&')[0]
                    response = self._download_from_drive(file_id, temp_file)
                    
                    def save_with_progress():
                        CHUNK_SIZE = 32768
                        total_size = int(response.headers.get('content-length', 0))
                        downloaded = 0
                        
                        with open(temp_file, "wb") as f:
                            for chunk in response.iter_content(CHUNK_SIZE):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if total_size > 0:
                                        percent = min(100, (downloaded * 100) / total_size)
                                        progress_var.set(percent)
                                        progress_dialog.update()
                    
                    save_with_progress()
                else:
                    # GitHub 다운로드
                    urllib.request.urlretrieve(download_url, temp_file, progress_hook)
                
                # 설치 스크립트 생성
                status_label.config(text="설치 준비 중...")
                progress_var.set(90)
                progress_dialog.update()
                
                current_exe = sys.executable if getattr(sys, 'frozen', False) else __file__
                batch_script = os.path.join(temp_dir, "update_akeo.bat")
                
                with open(batch_script, 'w', encoding='utf-8') as f:
                    f.write(f'''@echo off
echo 업데이트 설치 중...
timeout /t 2 /nobreak >nul
taskkill /f /im "akeo_slicer.exe" >nul 2>&1
copy "{temp_file}" "{current_exe}" /y
if exist "{temp_file}" del "{temp_file}"
if exist "{batch_script}" del "{batch_script}"
start "" "{current_exe}"
''')
                
                # 설치 실행
                status_label.config(text="설치 중... 프로그램이 재시작됩니다.")
                progress_var.set(100)
                progress_dialog.update()
                
                # 배치 파일 실행 후 현재 프로그램 종료
                subprocess.Popen([batch_script], shell=True)
                
                # 현재 프로그램 종료
                progress_dialog.after(1000, lambda: self.parent.quit())
                
            except Exception as e:
                progress_dialog.destroy()
                messagebox.showerror("업데이트 실패", 
                                   f"자동 업데이트에 실패했습니다.\n{str(e)}\n\n수동으로 다운로드해주세요.")
                self._open_download_page(download_url)
        
        # 별도 스레드에서 다운로드 실행
        import threading
        thread = threading.Thread(target=download_and_install, daemon=True)
        thread.start()
    
    def _manual_download(self, dialog, download_url):
        """수동 다운로드"""
        dialog.destroy()
        self._open_download_page(download_url)
    
    def _open_download_page(self, url):
        """다운로드 페이지 열기"""
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("오류", f"다운로드 페이지를 열 수 없습니다.\n{str(e)}")

def check_for_updates_on_startup(parent):
    """시작 시 자동 업데이트 확인"""
    def check_async():
        try:
            updater = AutoUpdater(parent)
            updater.check_updates(show_no_update=False)
        except:
            pass  # 조용히 실패
    
    # 별도 스레드에서 실행
    import threading
    thread = threading.Thread(target=check_async, daemon=True)
    thread.start()

if __name__ == '__main__':
    main()
