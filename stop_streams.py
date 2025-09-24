#!/usr/bin/env python3
"""
RTSP 스트림 중지 관리자
기존 stop_all_streams.sh 스크립트를 파이썬으로 리팩토링한 버전
"""

import os
import sys
import time
import signal
import subprocess
import shutil
import glob
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import logging
import logging.handlers

# 로깅 설정
def setup_logging(debug: bool = False, use_syslog: bool = True):
    """로깅 설정 함수"""
    # 로그 레벨 설정
    log_level = logging.DEBUG if debug else logging.INFO
    
    # 포맷터 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 핸들러 리스트
    handlers = []
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)
    
    # 파일 핸들러
    file_handler = logging.FileHandler('stop_streams.log')
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)
    
    # syslog 핸들러 (선택적)
    if use_syslog:
        try:
            syslog_handler = logging.handlers.SysLogHandler(address='/dev/log')
            syslog_formatter = logging.Formatter(
                'stop_streams[%(process)d]: %(levelname)s - %(message)s'
            )
            syslog_handler.setFormatter(syslog_formatter)
            handlers.append(syslog_handler)
        except Exception as e:
            print(f"syslog 핸들러 설정 실패: {e}")
    
    # 로깅 설정
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        force=True
    )
    
    return logging.getLogger(__name__)

# 기본 로깅 설정 (명령행 인자로 오버라이드 가능)
logger = setup_logging()


@dataclass
class StreamConfig:
    """스트림 설정 정보"""
    stream_id: int
    temp_output_path: str
    final_output_path: str
    env_file: str


class SessionManager:
    """Screen 세션 관리 클래스"""
    
    def __init__(self):
        self.base_session_name = "rtsp_stream"
        self.file_mover_session = "rtsp_file_mover"
    
    def get_running_sessions(self) -> Dict[str, int]:
        """실행 중인 세션 수 확인"""
        logger.debug("실행 중인 screen 세션 확인 중...")
        try:
            result = subprocess.run(['screen', '-list'], 
                                  capture_output=True, text=True, check=True)
            output = result.stdout
            logger.debug(f"screen -list 출력: {output}")
            
            running_streams = len([line for line in output.split('\n') 
                                 if self.base_session_name in line])
            running_mover = len([line for line in output.split('\n') 
                               if self.file_mover_session in line])
            
            logger.debug(f"발견된 세션 - 스트림: {running_streams}, 파일이동기: {running_mover}")
            
            return {
                'streams': running_streams,
                'mover': running_mover,
                'total': running_streams + running_mover
            }
        except subprocess.CalledProcessError as e:
            # screen이 설치되어 있지만 세션이 없는 경우 (return code 1)
            if e.returncode == 1:
                logger.debug("실행 중인 screen 세션이 없습니다")
                return {'streams': 0, 'mover': 0, 'total': 0}
            else:
                logger.warning(f"screen 명령어 실행 실패: {e}")
                return {'streams': 0, 'mover': 0, 'total': 0}
        except FileNotFoundError:
            logger.warning("screen 명령어를 찾을 수 없습니다 (screen이 설치되지 않음)")
            return {'streams': 0, 'mover': 0, 'total': 0}
    
    def stop_stream_sessions(self, num_streams: int = 6) -> int:
        """스트림 세션들 중지"""
        logger.debug(f"스트림 세션 중지 시작 - 대상: {num_streams}개")
        stopped_count = 0
        
        for i in range(1, num_streams + 1):
            session_name = f"{self.base_session_name}{i}"
            logger.debug(f"세션 {session_name} 처리 중...")
            
            try:
                # 세션 존재 확인
                result = subprocess.run(['screen', '-list'], 
                                      capture_output=True, text=True)
                if session_name not in result.stdout:
                    logger.debug(f"세션 {session_name}이 실행 중이지 않음")
                    continue
                
                logger.info(f"세션 중지 중: {session_name}")
                
                # 세션 종료
                subprocess.run(['screen', '-S', session_name, '-X', 'quit'], 
                             check=True)
                logger.debug(f"세션 {session_name}에 quit 신호 전송됨")
                
                # 중지 확인
                time.sleep(1)
                result = subprocess.run(['screen', '-list'], 
                                      capture_output=True, text=True)
                
                if session_name not in result.stdout:
                    logger.info(f"세션 중지 성공: {session_name}")
                    stopped_count += 1
                else:
                    logger.error(f"세션 중지 실패: {session_name}")
                    
            except subprocess.CalledProcessError as e:
                logger.error(f"세션 {session_name} 중지 중 오류 발생: {e}")
        
        logger.debug(f"세션 중지 완료 - 성공: {stopped_count}/{num_streams}")
        return stopped_count
    
    def stop_file_mover_session(self) -> bool:
        """파일 이동기 세션 중지"""
        logger.debug(f"파일 이동기 세션 중지 시작: {self.file_mover_session}")
        try:
            result = subprocess.run(['screen', '-list'], 
                                  capture_output=True, text=True)
            if self.file_mover_session not in result.stdout:
                logger.debug("파일 이동기 세션이 실행 중이지 않음")
                return True
            
            logger.info(f"파일 이동기 세션 중지 중: {self.file_mover_session}")
            subprocess.run(['screen', '-S', self.file_mover_session, '-X', 'quit'], 
                         check=True)
            logger.debug("파일 이동기 세션에 quit 신호 전송됨")
            time.sleep(1)
            
            result = subprocess.run(['screen', '-list'], 
                                  capture_output=True, text=True)
            success = self.file_mover_session not in result.stdout
            
            if success:
                logger.info("파일 이동기 세션 중지 성공")
            else:
                logger.error("파일 이동기 세션 중지 실패")
                
            return success
            
        except subprocess.CalledProcessError as e:
            logger.warning(f"파일 이동기 세션 중지 중 오류 발생 (screen 명령어 문제): {e}")
            return False
        except FileNotFoundError:
            logger.warning("screen 명령어를 찾을 수 없습니다 (screen이 설치되지 않음)")
            return False


class ProcessManager:
    """프로세스 관리 클래스"""
    
    @staticmethod
    def get_rtsp_stream_pids() -> List[int]:
        """rtsp_stream 세션의 종료 대상 child process ID 목록 가져오기
        - screen PID의 전체 자손 중에서 종료 타겟을 선별한다
        """
        child_pids = []
        try:
            # screen -list로 세션 목록 가져오기
            result = subprocess.run(['screen', '-list'], 
                                  capture_output=True, text=True, check=True)
            
            for line in result.stdout.split('\n'):
                if 'rtsp_stream' in line and ('Detached' in line or 'Attached' in line):
                    # 세션 이름에서 screen PID 추출 (예: "50214.rtsp_stream6")
                    parts = line.split('.')
                    if len(parts) >= 2:
                        try:
                            screen_pid = int(parts[0].strip())
                            session_status = 'Attached' if 'Attached' in line else 'Detached'
                            logger.debug(f"발견된 rtsp_stream 세션 screen PID: {screen_pid} (상태: {session_status})")
                            
                            # screen 세션의 종료 타겟 child PID 선택
                            target_pid = ProcessManager._select_target_child_pid(screen_pid)
                            if target_pid:
                                child_pids.append(target_pid)
                                logger.debug(f"screen PID {screen_pid}의 종료 타겟 PID: {target_pid}")
                            else:
                                logger.warning(f"screen PID {screen_pid}의 종료 타겟 child를 찾을 수 없습니다")
                                
                        except ValueError:
                            logger.debug(f"PID 파싱 실패: {line}")
                            
        except subprocess.CalledProcessError as e:
            # screen이 설치되어 있지만 세션이 없는 경우 (return code 1)
            if e.returncode == 1:
                logger.debug("실행 중인 screen 세션이 없습니다")
            else:
                logger.warning(f"screen -list 실행 실패: {e}")
        except FileNotFoundError:
            logger.warning("screen 명령어를 찾을 수 없습니다 (screen이 설치되지 않음)")
        except Exception as e:
            logger.warning(f"rtsp_stream PID 수집 중 오류: {e}")
            
        logger.debug(f"총 {len(child_pids)}개의 rtsp_stream child process PID 발견")
        return child_pids
    
    @staticmethod
    def get_screen_child_pid(screen_pid: int) -> Optional[int]:
        """screen 세션의 child process PID 찾기"""
        try:
            # ps 명령어로 screen의 child process 찾기
            result = subprocess.run(['ps', '--ppid', str(screen_pid), '-o', 'pid', '--no-headers'], 
                                  capture_output=True, text=True, check=True)
            
            if result.stdout.strip():
                # 첫 번째 child process PID 반환
                child_pid = int(result.stdout.strip().split('\n')[0])
                logger.debug(f"screen PID {screen_pid}의 child process: {child_pid}")
                return child_pid
            else:
                logger.debug(f"screen PID {screen_pid}의 child process가 없습니다")
                return None
                
        except subprocess.CalledProcessError as e:
            logger.debug(f"screen PID {screen_pid}의 child process 확인 실패: {e}")
            return None
        except Exception as e:
            logger.debug(f"screen PID {screen_pid}의 child process 확인 중 오류: {e}")
            return None
    
    @staticmethod
    def _build_process_maps() -> Tuple[Dict[int, List[int]], Dict[int, str]]:
        """시스템의 PPID->children, PID->cmdline 맵 구성"""
        ppid_to_children: Dict[int, List[int]] = {}
        pid_to_cmd: Dict[int, str] = {}
        try:
            ps = subprocess.run(
                ['ps', '-e', '-o', 'pid=', '-o', 'ppid=', '-o', 'args='],
                capture_output=True, text=True, check=True
            )
            for line in ps.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # pid ppid args
                parts = line.split(None, 2)
                if len(parts) < 2:
                    continue
                try:
                    pid_val = int(parts[0])
                    ppid_val = int(parts[1])
                except ValueError:
                    continue
                cmdline = parts[2] if len(parts) >= 3 else ''
                pid_to_cmd[pid_val] = cmdline
                ppid_to_children.setdefault(ppid_val, []).append(pid_val)
        except subprocess.CalledProcessError as e:
            logger.debug(f"ps 목록 수집 실패: {e}")
        return ppid_to_children, pid_to_cmd
    
    @staticmethod
    def _collect_descendants(root_pid: int, ppid_to_children: Dict[int, List[int]]) -> List[int]:
        """주어진 PID의 모든 하위 자손 PID 수집 (BFS)"""
        descendants: List[int] = []
        queue: List[int] = [root_pid]
        seen = set([root_pid])
        while queue:
            current = queue.pop(0)
            for child in ppid_to_children.get(current, []):
                if child in seen:
                    continue
                seen.add(child)
                descendants.append(child)
                queue.append(child)
        return descendants

    @staticmethod
    def _collect_descendants_with_depth(root_pid: int, ppid_to_children: Dict[int, List[int]]) -> Dict[int, int]:
        """주어진 PID의 모든 하위 자손 PID와 깊이 수집 (BFS) -> {pid: depth}"""
        depth_map: Dict[int, int] = {}
        queue: List[Tuple[int, int]] = [(root_pid, 0)]
        seen = set([root_pid])
        while queue:
            current, depth = queue.pop(0)
            for child in ppid_to_children.get(current, []):
                if child in seen:
                    continue
                seen.add(child)
                depth_map[child] = depth + 1
                queue.append((child, depth + 1))
        return depth_map
    
    @staticmethod
    def _select_target_child_pid(screen_pid: int) -> Optional[int]:
        """screen PID로부터 실제 종료 대상(child) PID 선택
        우선순위:
        1) cmdline에 'run.py' 포함하는 python/uv 프로세스
        2) python 또는 uv 프로세스
        3) 자식이 더 없는 리프 프로세스(가장 말단)
        """
        ppid_to_children, pid_to_cmd = ProcessManager._build_process_maps()
        depth_map = ProcessManager._collect_descendants_with_depth(screen_pid, ppid_to_children)
        if not depth_map:
            logger.debug(f"screen PID {screen_pid}의 자손 프로세스가 없습니다")
            return None
        
        def score_cmdline(cmd: str) -> int:
            score = 0
            if 'run.py' in cmd:
                score += 100
            if 'python' in cmd or 'python3' in cmd:
                score += 60
            if ' uv ' in f" {cmd} ":
                score += 50
            # 불필요 타겟 패널티
            for shell in [' bash', ' sh ', ' screen', ' pstree', ' ps ']:
                if shell in f" {cmd} ":
                    score -= 100
            return score

        # 후보 정렬: (score, depth) 내림차순
        candidates = []
        for pid, depth in depth_map.items():
            cmd = pid_to_cmd.get(pid, '')
            candidates.append((pid, score_cmdline(cmd), depth, cmd))

        # 높은 점수 우선, 점수 동일 시 더 깊은 것 우선
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        for pid, sc, depth, cmd in candidates:
            if sc > 0:
                logger.debug(f"선택 후보 PID {pid} (score={sc}, depth={depth}, cmd='{cmd}')")
                return pid

        # 점수 기준 후보가 없으면 리프(가장 깊은) 선택
        if candidates:
            pid, sc, depth, cmd = candidates[0]
            logger.debug(f"점수 후보 없음, 최심부 후보 선택 PID {pid} (depth={depth}, cmd='{cmd}')")
            return pid
        return None
    
    @staticmethod
    def kill_processes_by_pid(pids: List[int], grace_period: int = 5) -> bool:
        """PID 목록으로 프로세스 그레이스풀 종료"""
        if not pids:
            logger.debug("종료할 프로세스가 없습니다")
            return True
            
        logger.info(f"프로세스 {len(pids)}개에 SIGTERM 전송(그레이스풀 종료 유도)")
        logger.debug(f"대상 PID: {pids}, 그레이스 기간: {grace_period}초")
        
        # SIGTERM 전송
        for pid in pids:
            try:
                logger.debug(f"PID {pid}에 SIGTERM 전송")
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                logger.debug(f"PID {pid}가 이미 종료됨")
            except PermissionError:
                logger.warning(f"PID {pid}에 대한 권한이 없습니다")
            except Exception as e:
                logger.warning(f"PID {pid} 종료 신호 전송 실패: {e}")
        
        # 그레이스 기간 대기
        logger.debug("그레이스 기간 대기 시작")
        for sec in range(1, grace_period + 1):
            running_pids = []
            for pid in pids:
                try:
                    # 프로세스 존재 확인
                    os.kill(pid, 0)  # 신호 0은 프로세스 존재 확인용
                    running_pids.append(pid)
                    logger.debug(f"실행 중인 프로세스: PID {pid}")
                except ProcessLookupError:
                    logger.debug(f"PID {pid}가 종료됨")
                except Exception as e:
                    logger.debug(f"PID {pid} 확인 중 오류: {e}")
            
            if not running_pids:
                logger.debug("모든 프로세스가 종료됨")
                break
            
            logger.info(f"프로세스 종료 대기 중 {sec}/{grace_period}초... (남은 PID: {running_pids})")
            time.sleep(1)
        
        # 강제 종료가 필요한 프로세스 확인
        remaining_pids = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                remaining_pids.append(pid)
            except ProcessLookupError:
                pass
            except Exception:
                pass
        
        if remaining_pids:
            logger.warning(f"그레이스풀 종료 실패, 강제 종료 시도: PID {remaining_pids}")
            for pid in remaining_pids:
                try:
                    logger.debug(f"PID {pid}에 SIGKILL 전송")
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    logger.debug(f"PID {pid}가 이미 종료됨")
                except Exception as e:
                    logger.error(f"PID {pid} 강제 종료 실패: {e}")
        
        # 최종 확인
        final_running = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                final_running.append(pid)
            except ProcessLookupError:
                pass
            except Exception:
                pass
        
        final_result = len(final_running) == 0
        logger.debug(f"프로세스 종료 결과: {'성공' if final_result else '실패'}")
        if final_running:
            logger.error(f"여전히 실행 중인 프로세스: PID {final_running}")
        
        return final_result


class FileProcessor:
    """파일 처리 클래스"""
    
    def __init__(self, script_dir: str, profile: str = "sim"):
        self.script_dir = Path(script_dir)
        self.profile = profile
        self.env_base_dir = self.script_dir / "profiles" / profile
        self.alt_env_dir = self.script_dir
    
    def get_env_value(self, key: str, env_file: str) -> Optional[str]:
        """환경 파일에서 값 추출"""
        logger.debug(f"환경 파일에서 값 추출: {key} from {env_file}")
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    if line.startswith(f"{key}="):
                        value = line.split('=', 1)[1].strip()
                        logger.debug(f"환경 변수 {key} = {value}")
                        return value
        except FileNotFoundError:
            logger.debug(f"환경 파일을 찾을 수 없음: {env_file}")
        except Exception as e:
            logger.error(f"환경 파일 읽기 중 오류: {e}")
        return None
    
    def get_stream_config(self, stream_id: int) -> StreamConfig:
        """스트림 설정 정보 가져오기"""
        logger.debug(f"스트림 {stream_id} 설정 정보 가져오기")
        env_file = self.env_base_dir / f".env.stream{stream_id}"
        if not env_file.exists():
            env_file = self.alt_env_dir / f".env.stream{stream_id}"
            logger.debug(f"대체 환경 파일 사용: {env_file}")
        
        temp_output_path = "./output/temp/"
        final_output_path = "/mnt/nas/cam"
        
        if env_file.exists():
            logger.debug(f"환경 파일에서 경로 설정 읽기: {env_file}")
            temp_path = self.get_env_value("TEMP_OUTPUT_PATH", str(env_file))
            final_path = self.get_env_value("FINAL_OUTPUT_PATH", str(env_file))
            
            if temp_path:
                temp_output_path = temp_path
                logger.debug(f"임시 출력 경로: {temp_output_path}")
            if final_path:
                final_output_path = final_path
                logger.debug(f"최종 출력 경로: {final_output_path}")
        else:
            logger.warning(f"환경 파일을 찾을 수 없음: {env_file}, 기본값 사용")
        
        config = StreamConfig(
            stream_id=stream_id,
            temp_output_path=temp_output_path,
            final_output_path=final_output_path,
            env_file=str(env_file)
        )
        logger.debug(f"스트림 {stream_id} 설정: {config}")
        return config
    
    def is_file_stable(self, file_path: str, check_count: int = 3, 
                      max_wait: int = 15) -> bool:
        """파일 크기 안정화 확인"""
        if not os.path.exists(file_path):
            return False
        
        prev_size = -1
        same_count = 0
        
        for _ in range(max_wait):
            try:
                current_size = os.path.getsize(file_path)
                if current_size == prev_size and prev_size >= 0:
                    same_count += 1
                    if same_count >= check_count:
                        return True
                else:
                    same_count = 0
                    prev_size = current_size
            except OSError:
                return False
            
            time.sleep(1)
        
        return False
    
    def is_file_in_use(self, file_path: str) -> bool:
        """파일 사용 중인지 확인 (lsof 사용)"""
        try:
            result = subprocess.run(['lsof', file_path], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    
    def process_temp_files(self, config: StreamConfig) -> int:
        """임시 파일 처리 (이름 변경)"""
        temp_path = Path(config.temp_output_path)
        if not temp_path.exists():
            return 0
        
        processed_count = 0
        
        # MP4 파일 처리
        mp4_files = list(temp_path.glob("temp_*.mp4"))
        if mp4_files:
            logger.info(f"스트림 {config.stream_id}: {temp_path} 내 temp_ MP4 처리 {len(mp4_files)}개")
            
            for file_path in mp4_files:
                if self._process_single_file(file_path, config):
                    processed_count += 1
        
        # SRT 파일 처리
        srt_files = list(temp_path.glob("temp_*.srt"))
        if srt_files:
            logger.info(f"스트림 {config.stream_id}: {temp_path} 내 temp_ SRT 처리 {len(srt_files)}개")
            
            for file_path in srt_files:
                if self._process_single_file(file_path, config):
                    processed_count += 1
        
        return processed_count
    
    def _process_single_file(self, file_path: Path, config: StreamConfig) -> bool:
        """단일 파일 처리"""
        base_name = file_path.name
        final_name = base_name[5:]  # "temp_" 제거
        
        # 파일 크기 안정화 대기
        if not self.is_file_stable(str(file_path)):
            logger.warning(f"크기 불안정: {base_name} (rename 보류)")
            return False
        
        # 파일 사용 중인지 확인
        if self.is_file_in_use(str(file_path)):
            logger.warning(f"파일 핸들 열림 상태: {base_name} (rename 보류)")
            return False
        
        # 파일 이름 변경
        try:
            new_path = file_path.parent / final_name
            file_path.rename(new_path)
            logger.info(f"▶ {base_name} → {final_name}")
            return True
        except OSError as e:
            logger.error(f"이름 변경 실패: {base_name} - {e}")
            return False
    
    def final_sweep_move(self, config: StreamConfig) -> int:
        """최종 스윕 이동 (패턴 기반 최종 경로로 이동)"""
        temp_path = Path(config.temp_output_path)
        if not temp_path.exists():
            return 0
        
        moved_count = 0
        pattern = re.compile(r'_(\d{6})_(\d{6})\.(mp4|srt)$')
        
        for file_path in temp_path.glob("*"):
            if file_path.name.startswith("temp_"):
                continue
            
            match = pattern.search(file_path.name)
            if not match:
                continue
            
            date_part = match.group(1)
            time_part = match.group(2)
            file_ext = match.group(3)
            
            # 날짜/시간 파싱
            year = int(date_part[:2]) + 2000
            month = date_part[2:4]
            day = date_part[4:6]
            hour = time_part[:2]
            
            # 대상 디렉토리 생성
            target_dir = Path(config.final_output_path) / str(year) / month / day / hour
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # 파일 이동
            try:
                target_path = target_dir / file_path.name
                file_path.rename(target_path)
                logger.info(f"▶ 스윕 이동: {file_path.name} → {target_dir}/")
                moved_count += 1
            except OSError as e:
                logger.error(f"파일 이동 실패: {file_path.name} - {e}")
        
        return moved_count


class MediaMTXManager:
    """MediaMTX 관리 클래스"""
    
    @staticmethod
    def stop_mediamtx() -> bool:
        """MediaMTX 인스턴스 중지"""
        logger.info("MediaMTX 인스턴스 중지 시작")
        logger.debug("MediaMTX 프로세스 확인 중...")
        
        try:
            # MediaMTX 프로세스 확인
            result = subprocess.run(['pgrep', '-f', 'mediamtx'], 
                                  capture_output=True, text=True)
            if result.returncode != 0:
                logger.info("실행 중인 MediaMTX 인스턴스가 없습니다")
                return True
            
            logger.debug(f"발견된 MediaMTX 프로세스: {result.stdout.strip()}")
            logger.info("MediaMTX 정상 종료 시도")
            
            # 정상 종료 시도
            logger.debug("MediaMTX에 SIGTERM 전송")
            result = subprocess.run(['pkill', '-TERM', '-f', 'mediamtx'], 
                                  check=False, capture_output=True, text=True)
            
            # pkill 결과 로깅
            if result.returncode != 0:
                logger.debug(f"MediaMTX pkill 결과: returncode={result.returncode}")
                if result.stderr:
                    logger.debug(f"MediaMTX pkill stderr: {result.stderr.strip()}")
            else:
                logger.debug("MediaMTX pkill 성공")
            
            time.sleep(3)
            
            # 강제 종료 확인
            result = subprocess.run(['pgrep', '-f', 'mediamtx'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                logger.warning("정상 종료 실패, 강제 종료 시도")
                logger.debug("MediaMTX에 SIGKILL 전송")
                result = subprocess.run(['pkill', '-9', '-f', 'mediamtx'], 
                                      check=False, capture_output=True, text=True)
                
                # 강제 종료 결과 로깅
                if result.returncode != 0:
                    logger.debug(f"MediaMTX 강제 종료 결과: returncode={result.returncode}")
                    if result.stderr:
                        logger.debug(f"MediaMTX 강제 종료 stderr: {result.stderr.strip()}")
                else:
                    logger.debug("MediaMTX 강제 종료 성공")
                    
                logger.info("MediaMTX 강제 종료 완료")
            else:
                logger.info("MediaMTX 정상 종료 완료")
            
            return True
            
        except Exception as e:
            logger.error(f"MediaMTX 중지 중 오류 발생: {e}")
            return False


class StreamStopManager:
    """메인 스트림 중지 관리자"""
    
    def __init__(self, script_dir: str = None, profile: str = "sim"):
        self.script_dir = Path(script_dir) if script_dir else Path.cwd()
        self.profile = profile
        
        self.session_manager = SessionManager()
        self.process_manager = ProcessManager()
        self.file_processor = FileProcessor(str(self.script_dir), profile)
        self.mediamtx_manager = MediaMTXManager()
    
    def cleanup_temp_files(self) -> int:
        """임시 파일 정리"""
        logger.info("임시 파일 정리 시작")
        logger.debug(f"정리 대상 디렉토리: {self.script_dir}")
        
        temp_files_removed = 0
        
        # 임시 .env 파일 정리
        for i in range(1, 7):
            temp_file = self.script_dir / f".env.temp{i}"
            if temp_file.exists():
                logger.debug(f"임시 파일 발견: {temp_file.name}")
                temp_file.unlink()
                logger.info(f"임시 파일 삭제: {temp_file.name}")
                temp_files_removed += 1
            else:
                logger.debug(f"임시 파일 없음: {temp_file.name}")
        
        # 임시 .env 파일 정리
        env_file = self.script_dir / ".env"
        if env_file.exists():
            logger.debug("임시 .env 파일 발견")
            env_file.unlink()
            logger.info("임시 .env 파일 삭제")
            temp_files_removed += 1
        
        logger.debug(f"총 삭제된 임시 파일: {temp_files_removed}개")
        return temp_files_removed
    
    def stop_all_streams(self, num_streams: int = 6) -> Dict[str, any]:
        """모든 스트림 중지"""
        logger.info(f"RTSP 스트림 중지 시작 - 대상: {num_streams}개")
        logger.debug(f"스트림 중지 프로세스 시작 - 프로필: {self.profile}")
        
        # 실행 중인 세션 확인
        sessions = self.session_manager.get_running_sessions()
        logger.info("실행 중인 세션 확인")
        
        if sessions['total'] == 0:
            logger.info("실행 중인 세션이 없습니다")
        else:
            logger.info(f"RTSP 스트림 세션: {sessions['streams']}개")
            logger.info(f"파일 이동 세션: {sessions['mover']}개")
            logger.debug(f"총 세션 수: {sessions['total']}개")
        
        # rtsp_stream 세션의 Python 프로세스 그레이스풀 종료
        rtsp_pids = self.process_manager.get_rtsp_stream_pids()
        if rtsp_pids:
            logger.info(f"rtsp_stream 세션에서 {len(rtsp_pids)}개 프로세스 발견")
            success = self.process_manager.kill_processes_by_pid(rtsp_pids, grace_period=5)
            if success:
                logger.info("rtsp_stream 프로세스들이 성공적으로 종료되어 세션도 자동으로 종료됩니다")
                stopped_count = len(rtsp_pids)  # 종료된 프로세스 수를 세션 수로 간주
            else:
                logger.warning("일부 rtsp_stream 프로세스가 종료되지 않았습니다")
                stopped_count = 0
        else:
            logger.info("rtsp_stream 세션에서 실행 중인 프로세스가 없습니다")
            stopped_count = 0
        
        # 파일 처리
        if stopped_count > 0:
            logger.info("📦 저장 중 파일 정리(이름 변경) 진행...")
            
            total_processed = 0
            for i in range(1, num_streams + 1):
                config = self.file_processor.get_stream_config(i)
                processed = self.file_processor.process_temp_files(config)
                total_processed += processed
            
            # 파일 이동기 처리 대기
            logger.info("파일 이동기 처리 대기...")
            time.sleep(3)
            
            # 최종 스윕 반복 수행
            logger.info("🔁 최종 스윕 반복 수행...")
            final_sweep_max = int(os.environ.get('FINAL_SWEEP_SECONDS', '20'))
            
            for pass_num in range(1, final_sweep_max + 1):
                moved_count = 0
                for i in range(1, num_streams + 1):
                    config = self.file_processor.get_stream_config(i)
                    moved_count += self.file_processor.final_sweep_move(config)
                
                if moved_count == 0:
                    logger.info(f"(pass {pass_num}/{final_sweep_max}) 추가 이동 없음")
                    break
                else:
                    logger.info(f"(pass {pass_num}/{final_sweep_max}) 이동 처리: {moved_count}")
                    time.sleep(1)
        
        # 임시 파일 정리
        temp_files_removed = self.cleanup_temp_files()
        
        # 결과 출력
        logger.info("📊 중지 결과:")
        logger.info(f"   중지된 세션: {stopped_count} / {num_streams}")
        logger.info(f"   정리된 임시 파일: {temp_files_removed} 개")
        
        # 남은 세션 확인
        remaining_sessions = self.session_manager.get_running_sessions()
        if remaining_sessions['streams'] > 0:
            logger.warning("⚠️  아직 남은 세션이 있습니다:")
            logger.info("강제 종료하려면:")
            logger.info("   screen -wipe  # 죽은 세션 정리")
            logger.info("   pkill -f 'run.py'  # Python 프로세스 강제 종료")
        else:
            logger.info("✅ 모든 RTSP 스트림이 성공적으로 중지되었습니다!")
        
        # 파일 이동기 세션 중지
        logger.info("🔄 파일 이동 서비스 중지 중...")
        if self.session_manager.stop_file_mover_session():
            logger.info("파일 이동기 세션이 중지되었습니다.")
        
        # MediaMTX 중지
        self.mediamtx_manager.stop_mediamtx()
        
        # 기타 프로세스 정리
        logger.debug("기타 프로세스 정리 시작")
        try:
            # run_daemon.py 프로세스 정리
            logger.debug("run_daemon.py 프로세스 정리")
            result = subprocess.run(['pkill', '-TERM', '-f', 'run_daemon.py'], 
                                  check=False, capture_output=True, text=True)
            if result.returncode != 0:
                logger.debug(f"run_daemon.py pkill 결과: returncode={result.returncode}")
                if result.stderr:
                    logger.debug(f"run_daemon.py pkill stderr: {result.stderr.strip()}")
            else:
                logger.debug("run_daemon.py pkill 성공")
                
        except Exception as e:
            logger.warning(f"기타 프로세스 정리 중 오류: {e}")
        
        # 로그 파일 정보
        logger.info("📁 로그 파일들은 보존됩니다:")
        for i in range(1, num_streams + 1):
            log_file = self.script_dir / f"rtsp_stream{i}.log"
            if log_file.exists():
                file_size = log_file.stat().st_size
                logger.info(f"   {log_file.name} ({file_size} bytes)")
        
        return {
            'stopped_sessions': stopped_count,
            'temp_files_removed': temp_files_removed,
            'remaining_sessions': remaining_sessions['streams']
        }


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description='RTSP 스트림 중지 관리자')
    parser.add_argument('--profile', default='sim', 
                       help='프로필 설정 (기본값: sim)')
    parser.add_argument('--num-streams', type=int, default=6,
                       help='스트림 개수 (기본값: 6)')
    parser.add_argument('--script-dir', 
                       help='스크립트 디렉토리 (기본값: 현재 디렉토리)')
    parser.add_argument('--debug', action='store_true',
                       help='DEBUG 레벨 로깅 활성화')
    parser.add_argument('--no-syslog', action='store_true',
                       help='syslog 로깅 비활성화')
    
    args = parser.parse_args()
    
    # 스크립트 디렉토리 설정
    script_dir = args.script_dir or os.path.dirname(os.path.abspath(__file__))
    
    # 로깅 재설정
    global logger
    logger = setup_logging(debug=args.debug, use_syslog=not args.no_syslog)
    
    if args.debug:
        logger.debug("DEBUG 모드 활성화")
    if not args.no_syslog:
        logger.info("syslog 로깅 활성화")
    
    # 스트림 중지 관리자 생성 및 실행
    manager = StreamStopManager(script_dir, args.profile)
    
    try:
        result = manager.stop_all_streams(args.num_streams)
        
        if result['remaining_sessions'] == 0:
            logger.info("🎉 모든 작업이 성공적으로 완료되었습니다!")
            sys.exit(0)
        else:
            logger.warning("⚠️  일부 세션이 남아있습니다.")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("사용자에 의해 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
