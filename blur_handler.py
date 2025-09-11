"""
YOLO 블러 모듈 인터페이스

사용자 정의 YOLO 블러 모듈을 동적으로 로드하고 관리하는 인터페이스
- HeadBlurrer 클래스 로드
- 폴백 블러 처리
- 블러 설정 관리
"""

import cv2
import logging
import importlib.util
import numpy as np
from typing import Optional

try:
    from .config import RTSPConfig
except ImportError:
    from config import RTSPConfig

logger = logging.getLogger(__name__)

class BlurHandler:
    """YOLO 블러 모듈 인터페이스"""
    
    def __init__(self, config: RTSPConfig):
        self.config = config
        self.blur_module = None
        self.module_loaded = False
        self.load_blur_module()
    
    def load_blur_module(self):
        """사용자 블러 모듈 동적 로드"""
        if not self.config.blur_module_path:
            logger.info("블러 모듈 경로가 설정되지 않음, 기본 블러 사용")
            return
        
        try:
            logger.info(f"블러 모듈 로드 시도: {self.config.blur_module_path}")
            
            # 모듈 동적 로드
            spec = importlib.util.spec_from_file_location("blur_module", self.config.blur_module_path)
            blur_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(blur_module)
            
            # HeadBlurrer 클래스 확인 및 인스턴스 생성
            if hasattr(blur_module, 'HeadBlurrer'):
                # HeadBlurrer 클래스 인스턴스 생성
                head_blurrer = blur_module.HeadBlurrer()
                
                # apply_blur 메서드를 가진 래퍼 객체 생성
                class BlurWrapper:
                    def __init__(self, head_blurrer):
                        self.head_blurrer = head_blurrer
                    
                    def apply_blur(self, frame):
                        """프레임에 블러 처리 적용"""
                        return self.head_blurrer.process_frame(frame)
                    
                    def is_available(self):
                        """블러 모듈 사용 가능 여부"""
                        return hasattr(self.head_blurrer, 'process_frame')
                
                self.blur_module = BlurWrapper(head_blurrer)
                self.module_loaded = True
                logger.info("HeadBlurrer 클래스 로드 성공")
                
            elif hasattr(blur_module, 'apply_blur'):
                # 직접 apply_blur 함수가 있는 경우
                class FunctionWrapper:
                    def __init__(self, apply_blur_func):
                        self.apply_blur_func = apply_blur_func
                    
                    def apply_blur(self, frame):
                        return self.apply_blur_func(frame)
                    
                    def is_available(self):
                        return True
                
                self.blur_module = FunctionWrapper(blur_module.apply_blur)
                self.module_loaded = True
                logger.info("apply_blur 함수 로드 성공")
                
            else:
                logger.error("블러 모듈에 'HeadBlurrer' 클래스나 'apply_blur' 함수가 없습니다.")
                
        except Exception as e:
            logger.error(f"블러 모듈 로드 실패: {e}")
            import traceback
            logger.error(f"상세 오류: {traceback.format_exc()}")
    
    def apply_blur(self, frame: np.ndarray) -> np.ndarray:
        """프레임에 블러 처리 적용"""
        if not self.config.blur_enabled:
            return frame
        
        if frame is None:
            return frame
        
        try:
            if self.module_loaded and self.blur_module and self.blur_module.is_available():
                # 사용자 YOLO 모듈 사용
                return self.blur_module.apply_blur(frame)
            else:
                # 기본 블러 처리
                return self._apply_default_blur(frame)
                
        except Exception as e:
            logger.error(f"블러 처리 중 오류: {e}")
            # 오류 발생 시 기본 블러로 폴백
            return self._apply_default_blur(frame)
    
    def _apply_default_blur(self, frame: np.ndarray) -> np.ndarray:
        """기본 블러 처리 (YOLO 모듈이 없는 경우)"""
        try:
            # 간단한 가우시안 블러 적용
            return cv2.GaussianBlur(frame, (15, 15), 0)
        except Exception as e:
            logger.error(f"기본 블러 처리 오류: {e}")
            return frame
    
    def is_available(self) -> bool:
        """블러 모듈 사용 가능 여부"""
        return self.module_loaded and self.blur_module is not None
    
    def get_module_info(self) -> dict:
        """블러 모듈 정보 반환"""
        return {
            'module_path': self.config.blur_module_path,
            'module_loaded': self.module_loaded,
            'module_available': self.is_available(),
            'blur_enabled': self.config.blur_enabled,
            'confidence_threshold': self.config.blur_confidence
        }
    
    def reload_module(self):
        """블러 모듈 재로드"""
        logger.info("블러 모듈 재로드 시도")
        self.blur_module = None
        self.module_loaded = False
        self.load_blur_module()
    
    def set_confidence_threshold(self, threshold: float):
        """신뢰도 임계값 설정 (YOLO 모듈이 지원하는 경우)"""
        self.config.blur_confidence = threshold
        if hasattr(self.blur_module, 'set_confidence'):
            try:
                self.blur_module.set_confidence(threshold)
                logger.info(f"블러 모듈 신뢰도 임계값 설정: {threshold}")
            except Exception as e:
                logger.warning(f"신뢰도 임계값 설정 실패: {e}")
    
    def cleanup(self):
        """리소스 정리"""
        if self.blur_module:
            try:
                # 블러 모듈에 cleanup 메서드가 있는 경우 호출
                if hasattr(self.blur_module, 'cleanup'):
                    self.blur_module.cleanup()
                elif hasattr(self.blur_module, 'head_blurrer') and hasattr(self.blur_module.head_blurrer, 'cleanup'):
                    self.blur_module.head_blurrer.cleanup()
            except Exception as e:
                logger.warning(f"블러 모듈 정리 중 오류: {e}")
        
        self.blur_module = None
        self.module_loaded = False
        logger.info("블러 핸들러 정리 완료") 