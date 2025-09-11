import cv2
import time
from datetime import datetime
import os
import argparse
import numpy as np
import csv
import json
from dotenv import load_dotenv

# ultralytics 선택적 임포트
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("⚠️ ultralytics가 설치되지 않음 - 기본 블러 모드로 동작")

# .env 파일 로드
load_dotenv()

def get_model_path():
    """환경변수에서 HEAD_BLUR_MODEL_PATH를 가져오는 함수"""
    env_model_path = os.getenv('HEAD_BLUR_MODEL_PATH')
    if env_model_path:
        # 상대 경로인 경우 절대 경로로 변환
        if not os.path.isabs(env_model_path):
            # 현재 파일의 디렉토리 기준으로 프로젝트 루트 찾기
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)  # blur_module의 부모 디렉토리
            model_path = os.path.join(project_root, env_model_path)
        else:
            model_path = env_model_path
        
        print(f"✅ 환경변수에서 모델 경로 로드: {model_path}")
        return model_path
    else:
        # 기본 경로 (fallback)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_model_path = os.path.join(current_dir, "models", "best_re_final.pt")
        print(f"⚠️ 환경변수 HEAD_BLUR_MODEL_PATH가 없음. 기본 경로 사용: {default_model_path}")
        return default_model_path

class HeadBlurrer:
    def __init__(self, model_path=None, conf_threshold=0.3, enable_face_counting=False):
        """
        HeadBlurrer 초기화
        
        Args:
            model_path (str): PyTorch 모델 파일 경로 (None인 경우 환경변수에서 가져옴)
            conf_threshold (float): 탐지 신뢰도 임계값
            enable_face_counting (bool): 얼굴 탐지 수 기록 기능 활성화
        """
        # model_path가 None인 경우 환경변수에서 가져오기
        if model_path is None:
            self.model_path = get_model_path()
        else:
            self.model_path = model_path
        self.conf_threshold = conf_threshold  # 탐지 신뢰도 임계값
        self.enable_face_counting = enable_face_counting
        
        # 모델 로드
        self.model = self._load_model()
        print(f"✅ 모델 로드 완료: {model_path}")
        
        # 단일 카메라용 변수들
        self.frame_count = 0
        self.last_head_boxes = []
        
        # 얼굴 탐지 기록용 (테스트 기능)
        if self.enable_face_counting:
            self.detection_records = []  # 각 프레임의 탐지 정보 저장
            self.stats = {}  # 카메라별 통계
            print("🔍 얼굴 탐지 수 기록 기능 활성화")
    
    def _load_model(self):
        """PyTorch YOLO 모델 로드"""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {self.model_path}")
        
        try:
            model = YOLO(self.model_path)
            return model
        except Exception as e:
            raise RuntimeError(f"모델 로드 실패: {e}")
            
    def _detect_heads(self, image):
        """
        머리 탐지 수행
        

        Args:
            image: OpenCV 이미지 (BGR)
        
        Returns:
            list: 머리 바운딩 박스 좌표 리스트 [[x1,y1,x2,y2], ...]
        """
        try:
            # YOLO 추론 
            results = self.model(image, conf=self.conf_threshold, verbose=False)
            
            head_boxes = []
            if results[0].boxes is not None:
                # 바운딩 박스 좌표 추출
                boxes = results[0].boxes.xyxy.cpu().numpy()  # [x1, y1, x2, y2] 형태
                for box in boxes:
                    x1, y1, x2, y2 = box.astype(int)
                    head_boxes.append([x1, y1, x2, y2])
            else:
                print("탐지된 머리 없음")
            
            return head_boxes
            
        except Exception as e:
            print(f"⚠️  머리 탐지 중 오류: {e}")
            return []

    def _record_detection(self, frame_number, face_count, detection_performed=False):
        """
        얼굴 탐지 정보 기록 (테스트 기능)
        
        Args:
            frame_number: 프레임 번호
            face_count: 탐지된 얼굴 수
            detection_performed: 실제 탐지를 수행했는지 여부 (간격 탐지용)
        """
        if not self.enable_face_counting:
            return
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        record = {
            'timestamp': timestamp,
            'frame_number': frame_number,
            'face_count': face_count,
            'detection_performed': detection_performed,
            'confidence_threshold': self.conf_threshold
        }
        
        self.detection_records.append(record)
        
        # 통계 업데이트 (단일 카메라용)
        if not hasattr(self, 'stats'):
            self.stats = {
                'total_frames': 0,
                'total_faces': 0,
                'detection_frames': 0,
                'max_faces': 0,
                'avg_faces': 0.0
            }
        
        self.stats['total_frames'] += 1
        self.stats['total_faces'] += face_count
        if detection_performed:
            self.stats['detection_frames'] += 1
        self.stats['max_faces'] = max(self.stats['max_faces'], face_count)
        self.stats['avg_faces'] = self.stats['total_faces'] / self.stats['total_frames']

    def save_detection_records(self, output_dir="output", filename_prefix="face_detection"):
        """
        얼굴 탐지 기록을 파일로 저장 (테스트 기능)
        
        Args:
            output_dir: 저장 디렉토리
            filename_prefix: 파일명 접두사
        """
        if not self.enable_face_counting or not self.detection_records:
            print("⚠️ 저장할 얼굴 탐지 기록이 없습니다.")
            return
            
        # 출력 디렉토리 생성
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # CSV 파일로 상세 기록 저장
        csv_filename = f"{filename_prefix}_details_{timestamp}.csv"
        csv_path = os.path.join(output_dir, csv_filename)
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['timestamp', 'frame_number', 'face_count', 'detection_performed', 'confidence_threshold']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.detection_records)
            
        # JSON 파일로 통계 저장
        json_filename = f"{filename_prefix}_stats_{timestamp}.json"
        json_path = os.path.join(output_dir, json_filename)
        
        summary_data = {
            'generation_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'total_records': len(self.detection_records),
            'camera_statistics': self.stats,
            'overall_stats': {
                'total_frames_all_cameras': self.stats['total_frames'],
                'total_faces_all_cameras': self.stats['total_faces'],
                'cameras_count': 1 # 단일 카메라
            }
        }
        
        with open(json_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(summary_data, jsonfile, indent=2, ensure_ascii=False)
            
        print(f"📊 얼굴 탐지 기록 저장 완료:")
        print(f"   - 상세 기록: {csv_path} ({len(self.detection_records)}개 레코드)")
        print(f"   - 통계 요약: {json_path}")
        
        # 간단한 통계 출력
        print(f"   - 카메라 통계: {self.stats['total_frames']}프레임, 평균 {self.stats['avg_faces']:.1f}명, 최대 {self.stats['max_faces']}명")
    
    def _apply_blur_to_heads(self, image, head_boxes, blur_strength=0.01):
        """
        머리 영역에 블러 효과 적용 (배치 처리 최적화)
        
        Args:
            image: 원본 이미지
            head_boxes: 머리 바운딩 박스 리스트
            blur_strength: 블러 강도 (0.15 = 15% 크기로 축소)
        
        Returns:
            블러 처리된 이미지
        """
        if not head_boxes:
            return image
            
        result_image = image.copy()
        h, w = image.shape[:2]
        
        # 전체 이미지에 대해 한번만 블러 처리 (메모리 효율적)
        blur_h = max(1, int(h * blur_strength))
        blur_w = max(1, int(w * blur_strength))
        
        # 한번의 resize 연산으로 전체 이미지 블러 생성
        small_image = cv2.resize(image, (blur_w, blur_h), interpolation=cv2.INTER_LINEAR)
        blurred_full = cv2.resize(small_image, (w, h), interpolation=cv2.INTER_NEAREST)
        
        # 모든 head box 영역을 배치로 처리
        for box in head_boxes:
            x1, y1, x2, y2 = box
            
            # 좌표 범위 검증 및 정규화
            x1 = max(0, min(x1, w-1))
            y1 = max(0, min(y1, h-1))
            x2 = max(x1+1, min(x2, w))
            y2 = max(y1+1, min(y2, h))
            
            # 블러된 영역을 결과 이미지에 복사 (vectorized operation)
            if (x2 - x1) > 0 and (y2 - y1) > 0:
                result_image[y1:y2, x1:x2] = blurred_full[y1:y2, x1:x2]
        
        return result_image

    def process_frame(self, frame, frame_interval=1, blur_strength=0.01, should_detect=None):
        """
        n 프레임마다 탐지 수행, 그 외에는 이전 탐지 결과 사용
        
        Args:
            frame: 입력 프레임
            frame_interval: 탐지 간격 (should_detect가 None일 때만 사용)
            blur_strength: 블러 강도
            should_detect: 외부에서 탐지 여부 결정 (None이면 내부 간격 제어 사용)
        """
        detection_performed = False
        
        # 외부에서 탐지 여부를 명시적으로 지정한 경우 우선 사용
        if should_detect is not None:
            if should_detect:
                self.last_head_boxes = self._detect_heads(frame)
                detection_performed = True
        else:
            # 기존 방식: 내부 간격 제어
            if self.frame_count % frame_interval == 0:
                self.last_head_boxes = self._detect_heads(frame)
                detection_performed = True
            
        # 얼굴 탐지 기록 (테스트 기능)
        face_count = len(self.last_head_boxes)
        self._record_detection(
            frame_number=self.frame_count,
            face_count=face_count,
            detection_performed=detection_performed
        )
            
        self.frame_count += 1

        blurred_frame = self._apply_blur_to_heads(frame, self.last_head_boxes, blur_strength)
        return blurred_frame

def main():
    parser = argparse.ArgumentParser(description="IP 카메라 스트림 블러 처리")
    parser.add_argument(
        "-i", "--interval", type=int, default=3,
        help="머리 탐지를 수행할 프레임 간격 (기본값: 3)"
    )
    parser.add_argument(
        "-s", "--save", action="store_true",
        help="실행 중 전체 영상을 저장 (원본 및 블러 처리 영상)"
    )
    parser.add_argument(
        "--save-original", action="store_true",
        help="원본 영상만 저장"
    )
    parser.add_argument(
        "--save-blurred", action="store_true",
        help="블러 처리 영상만 저장"
    )

    parser.add_argument(
        "-c", "--confidence", type=float, default=0.2,
        help="머리 탐지 신뢰도 임계값 (기본값: 0.3)"
    )
    parser.add_argument(
        "-f", "--fps", type=float, default=15.0,
        help="비디오 FPS (기본값: 15.0)"
    )
    parser.add_argument(
        "-b", "--blur-strength", type=float, default=0.01,
        help="블러 강도 (기본값: 0.01, 범위: 0.01-1.0)"
    )
    
    # 얼굴 탐지 기록 기능 (테스트용)
    parser.add_argument(
        "--enable-face-counting", action="store_true",
        help="얼굴 탐지 수 기록 기능 활성화 (테스트용)"
    )
    parser.add_argument(
        "--face-count-output", type=str, default="output",
        help="얼굴 탐지 기록 저장 디렉토리 (기본값: output)"
    )

    args = parser.parse_args()
    
    # 환경변수에서 설정 읽기
    interval = args.interval
    
    # 환경변수에서 모델 경로 가져오기
    model_path = get_model_path()
    confidence_threshold = args.confidence
    rtsp_url = 'rtsp://root:root@192.168.1.101:554/cam0_0'  # 단일 카메라
    
    # 비디오/카메라 설정
    video_fps = args.fps
    video_codec = 'mp4v'
    output_dir = 'output'
    blur_strength = args.blur_strength
    enable_face_counting = args.enable_face_counting
    face_count_output_dir = args.face_count_output

    # 저장 설정 확인
    save_original = args.save or args.save_original
    save_blurred = args.save or args.save_blurred
    save_enabled = save_original or save_blurred

    # output 디렉토리 생성 (저장이 활성화된 경우)
    if save_enabled:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"✅ 출력 디렉토리 생성: {output_dir}")

    print(f"🔧 설정:")
    print(f"   - 모델 경로: {model_path}")
    print(f"   - 신뢰도 임계값: {confidence_threshold}")
    print(f"   - 탐지 간격: {interval}프레임")
    print(f"   - 블러 강도: {blur_strength}")
    print(f"   - 얼굴 탐지 기록: {'활성화' if enable_face_counting else '비활성화'}")
    if enable_face_counting:
        print(f"   - 기록 저장 경로: {face_count_output_dir}")
    print(f"   - 비디오 FPS: {video_fps}")
    print(f"   - 비디오 코덱: {video_codec}")
    print(f"   - 출력 디렉토리: {output_dir}")
    print(f"   - 카메라: {rtsp_url}")
    print(f"   - 저장 모드: {'활성화' if save_enabled else '비활성화'}")
    if save_enabled:
        save_types = []
        if save_original:
            save_types.append("원본")
        if save_blurred:
            save_types.append("블러")
        print(f"   - 저장 타입: {', '.join(save_types)}")

    cap = cv2.VideoCapture(rtsp_url)
    blurrer = HeadBlurrer(
        conf_threshold=confidence_threshold,
        enable_face_counting=enable_face_counting
    )

    if not cap.isOpened():
        print("카메라 스트림을 열 수 없습니다.")
        return
        
    # 저장 관련 변수 초기화
    out_original = None
    out_blurred = None

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter.fourcc(*video_codec)

    # 저장이 활성화된 경우 VideoWriter 설정
    if save_enabled:
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"📹 영상 저장 시작: {now}")
        
        if save_original:
            out_original = cv2.VideoWriter(
                os.path.join(output_dir, f"cam_original_{now}.mp4"), 
                fourcc, video_fps, (width, height)
            )
            print(f"   - 원본 영상: cam_original_{now}.mp4")
            
        if save_blurred:
            out_blurred = cv2.VideoWriter(
                os.path.join(output_dir, f"cam_blurred_{now}.mp4"), 
                fourcc, video_fps, (width, height)
            )
            print(f"   - 블러 영상: cam_blurred_{now}.mp4")

    try:
        while True:
            ret, frame = cap.read()
            
            if not ret:
                print("프레임을 읽을 수 없습니다.")
                break

            blurred_frame = blurrer.process_frame(frame, frame_interval=interval, blur_strength=blur_strength)
            cv2.imshow("IP Camera Stream", blurred_frame)
            
            # 저장이 활성화된 경우 프레임 저장
            if save_enabled:
                if save_original and out_original:
                    out_original.write(frame)
                
                if save_blurred and out_blurred:
                    out_blurred.write(blurred_frame)
            
            key = cv2.waitKey(1) & 0xFF
            # 'q' 키로 종료
            if key == ord('q'):
                print("🔴 종료 신호 수신")
                break
                
    except KeyboardInterrupt:
        print("🔴 사용자 중단 (Ctrl+C)")
    except Exception as e:
        print(f"⚠️ 오류 발생: {e}")
    finally:
        # 얼굴 탐지 기록 저장 (테스트 기능)
        if enable_face_counting:
            print("💾 얼굴 탐지 기록 저장 중...")
            blurrer.save_detection_records(output_dir=face_count_output_dir)

        # 리소스 해제
        print("🔄 리소스 정리 중...")
        cap.release()
        
        # VideoWriter 해제 및 저장 완료 메시지
        if save_enabled:
            saved_files = []
            if out_original:
                out_original.release()
                saved_files.append(f"cam_original_{now}.mp4")
            if out_blurred:
                out_blurred.release()
                saved_files.append(f"cam_blurred_{now}.mp4")
            
            print(f"✅ 영상 저장 완료:")
            for file in saved_files:
                print(f"   - {os.path.join(output_dir, file)}")
        
        cv2.destroyAllWindows()
        print("🏁 프로그램 종료")

if __name__ == "__main__":
    main()

# ─────────────────────────────────────────────────────────────
# rtsp_simulator_ffmpeg.py가 동적 로딩하는 apply_blur 래퍼
# ─────────────────────────────────────────────────────────────

_blurrer = HeadBlurrer(
    conf_threshold=0.3,
    enable_face_counting=False  # 기본적으로 비활성화
)

def apply_blur(frame,
               frame_interval: int = 3,
               blur_strength: float = 0.01,
               should_detect=None):
    """
    단일 카메라용 블러 적용 함수
    
    Args:
        frame: 입력 프레임
        frame_interval: 탐지 간격 (should_detect가 None일 때만 사용)
        blur_strength: 블러 강도
        should_detect: 외부에서 탐지 여부 결정 (None이면 내부 간격 제어 사용)
    
    Returns:
        블러 처리된 프레임
    """
    return _blurrer.process_frame(
        frame, 
        frame_interval=frame_interval,
        blur_strength=blur_strength,
        should_detect=should_detect
    )

def enable_face_counting_for_blurrer(enable=True, output_dir="output"):
    """
    단일 카메라용 얼굴 탐지 기록 기능 활성화/비활성화 (테스트용)
    
    Args:
        enable (bool): 기능 활성화 여부
        output_dir (str): 기록 저장 디렉토리
    """
    global _blurrer
    _blurrer.enable_face_counting = enable
    if enable:
        _blurrer.detection_records = []
        _blurrer.stats = {} # 단일 카메라용 통계 초기화
        print("🔍 단일 카메라용 얼굴 탐지 기록 기능 활성화")
    return output_dir

def save_face_counting_records(output_dir="output", filename_prefix="face_detection_wrapper"):
    """
    단일 카메라용 얼굴 탐지 기록 저장 (테스트용)
    
    Args:
        output_dir (str): 저장 디렉토리
        filename_prefix (str): 파일명 접두사
    """
    global _blurrer
    if _blurrer and _blurrer.enable_face_counting:
        _blurrer.save_detection_records(output_dir=output_dir, filename_prefix=filename_prefix)
        return True
    else:
        print("⚠️ 얼굴 탐지 기록 기능이 비활성화되어 있습니다.")
        return False
