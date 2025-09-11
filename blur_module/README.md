# 블러 모델 폴더 🎨

이 폴더는 RTSP 시뮬레이터에서 사용할 AI 기반 블러 처리 모듈과 모델 파일들을 저장하는 곳입니다.

## 📋 폴더 구조

```
blur_models/
├── README.md                    # 사용법 안내
├── .gitkeep                    # Git 추적용
├── example_blur_module.py      # 예시 블러 모듈
├── your_blur_module.py         # 사용자 커스텀 모듈
├── models/                     # AI 모델 파일들
│   ├── best_re_final.engine   # YOLO TensorRT 모델
│   ├── yolo_model.pt          # PyTorch 모델
│   └── config.yaml            # 모델 설정
└── utils/                      # 유틸리티 함수들
    ├── __init__.py
    └── image_processing.py
```

## 🔧 블러 모듈 구현

### 방법 1: HeadBlurrer 클래스 (권장)
YOLO 기반 얼굴 탐지 및 블러 처리를 위한 클래스입니다.

```python
# your_blur_module.py
import cv2
import numpy as np

class HeadBlurrer:
    def __init__(self, model_path: str, num_camera: int):
        """
        YOLO 기반 HeadBlurrer 초기화
        
        Args:
            model_path (str): 모델 파일 경로 (예: "best_re_final.engine")
            num_camera (int): 카메라 수 (현재는 사용하지 않음)
        """
        self.model_path = model_path
        self.num_camera = num_camera
        # 여기에 YOLO 모델 로드 코드 작성
        # self.model = load_your_model(model_path)
        
    def process_frame(self, frame: np.ndarray, camera_index: int) -> np.ndarray:
        """
        프레임에서 얼굴을 탐지하고 블러 처리
        
        Args:
            frame (np.ndarray): 입력 프레임
            camera_index (int): 카메라 인덱스 (0 고정)
            
        Returns:
            np.ndarray: 블러 처리된 프레임
        """
        # 1. 얼굴 탐지
        # faces = self.detect_faces(frame)
        
        # 2. 블러 처리
        # blurred_frame = self.apply_blur_to_faces(frame, faces)
        
        # 예시: 간단한 가우시안 블러
        return cv2.GaussianBlur(frame, (15, 15), 0)
```

### 방법 2: apply_blur 함수
간단한 함수 형태로 구현할 수도 있습니다.

```python
# simple_blur_module.py
import cv2
import numpy as np

def apply_blur(frame: np.ndarray, thread_id: int) -> np.ndarray:
    """
    프레임에 블러 효과 적용
    
    Args:
        frame (np.ndarray): 입력 프레임
        thread_id (int): 스레드 ID
        
    Returns:
        np.ndarray: 블러 처리된 프레임
    """
    # 커스텀 블러 처리 로직
    return cv2.GaussianBlur(frame, (21, 21), 0)
```

## 🚀 사용 방법

### 1. 모델 파일 준비
- YOLO 모델 파일을 `blur_models/models/` 폴더에 복사
- 지원 형식: `.pt`, `.engine`, `.onnx`, `.pb` 등

### 2. 블러 모듈 작성
- `HeadBlurrer` 클래스 또는 `apply_blur` 함수 구현
- 파일을 `blur_models/` 폴더에 저장

### 3. RTSP 시뮬레이터에서 설정
1. GUI에서 "🎨 사용자 블러 모듈 설정" 섹션으로 이동
2. "파일 선택" 버튼으로 블러 모듈 선택
3. 프로그램 실행 시 자동으로 스레드별 인스턴스 생성

## 🎯 지원 AI 프레임워크

### YOLO (권장)
```bash
pip install ultralytics  # YOLOv8/v11
pip install torch torchvision  # PyTorch
```

### TensorRT (고성능)
```bash
# NVIDIA GPU 환경에서 사용
pip install tensorrt
```

### OpenVINO (Intel)
```bash
pip install openvino
```

### ONNX Runtime
```bash
pip install onnxruntime-gpu  # GPU 버전
pip install onnxruntime      # CPU 버전
```

## 🔍 모델 파일 관리

### 지원 모델 형식
- **`.pt`**: PyTorch 모델
- **`.engine`**: TensorRT 최적화 모델
- **`.onnx`**: ONNX 범용 모델
- **`.pb`**: TensorFlow 모델
- **`.tflite`**: TensorFlow Lite 모델

### 성능 최적화
| 모델 형식 | 속도 | 호환성 | 권장 용도 |
|-----------|------|--------|-----------|
| .engine | ⭐⭐⭐⭐⭐ | NVIDIA만 | 고성능 실시간 |
| .onnx | ⭐⭐⭐⭐ | 범용 | 범용 배포 |
| .pt | ⭐⭐⭐ | PyTorch | 개발/테스트 |
| .pb | ⭐⭐ | TensorFlow | 레거시 |

## 💡 개발 팁

### 디버깅
```python
# 로깅 추가
import logging
logger = logging.getLogger(__name__)

def process_frame(self, frame, camera_index):
    logger.debug(f"Processing frame: {frame.shape}")
    # 처리 로직
    return processed_frame
```

### 성능 측정
```python
import time

def process_frame(self, frame, camera_index):
    start_time = time.time()
    # 처리 로직
    processed_frame = self.your_processing(frame)
    end_time = time.time()
    
    print(f"Processing time: {(end_time - start_time)*1000:.2f}ms")
    return processed_frame
```

### 메모리 관리
```python
# GPU 메모리 정리 (PyTorch)
import torch

def __del__(self):
    if hasattr(self, 'model') and self.model is not None:
        del self.model
        torch.cuda.empty_cache()
```

## 🚨 주의사항

- **모델 라이센스**: 사용하는 AI 모델의 라이센스를 확인하세요
- **GPU 메모리**: 큰 모델은 GPU 메모리 부족을 일으킬 수 있습니다
- **스레드 안전성**: 각 스레드마다 독립적인 모델 인스턴스가 생성됩니다
- **예외 처리**: 모델 로드나 추론 실패 시 기본 블러로 폴백됩니다

블러 모듈을 구현하여 AI 기반 실시간 영상 처리를 경험해보세요! 🎨✨ 