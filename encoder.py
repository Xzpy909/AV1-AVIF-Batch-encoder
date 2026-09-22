"""
encoder.py - Core Engine for AV1 Batch Encoder
Orchestrates FFmpeg 10-bit decoding pipes, SVT-AV1 encoding, MP4 container muxing,
ExifTool metadata copying (for videos), native avifenc photo encoding (with metadata & gain map support),
and multi-threaded Qt6 execution.
All processes are executed completely silently with zero console windows spawned.
"""

import os
import sys
import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

try:
    from PyQt6.QtCore import QThread, pyqtSignal
except ImportError:
    # Graceful fallback for non-GUI environments / CLI usage
    class QThread:
        def __init__(self):
            self._is_running = True
        def start(self):
            threading.Thread(target=self.run, daemon=True).start()
    def pyqtSignal(*types):
        class Signal:
            def __init__(self):
                self._cbs = []
            def connect(self, cb):
                self._cbs.append(cb)
            def emit(self, *args):
                for cb in self._cbs:
                    cb(*args)
        return Signal()


def get_app_root() -> Path:
    """Return application root directory (where main.py resides)."""
    return Path(__file__).resolve().parent


def get_subprocess_kwargs() -> Dict[str, Any]:
    """
    Ensures all subprocesses run completely silently without spawning
    or flashing any command prompt or console windows on Windows.
    """
    kwargs: Dict[str, Any] = {}
    if sys.platform.startswith("win"):
        # CREATE_NO_WINDOW prevents creation of a new console window (0x08000000)
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
            kwargs["startupinfo"] = startupinfo
    return kwargs


def resolve_tool_path(tool_name: str) -> str:
    """
    Locates required tool binary:
    (root)/tools/ffmpeg/ffmpeg.exe, ffprobe.exe
    (root)/tools/encoders/SvtAv1EncApp.exe
    (root)/tools/encoders/avifenc.exe
    (root)/tools/exiftool/exiftool.exe (video metadata only)
    Falls back to Linux executable and system PATH.
    """
    root = get_app_root()
    tools_dir = root / "tools"
    is_win = sys.platform.startswith("win")

    candidate_map = {
        "ffmpeg": [
            tools_dir / "ffmpeg" / ("ffmpeg.exe" if is_win else "ffmpeg"),
            tools_dir / "ffmpeg" / "ffmpeg.exe",
            tools_dir / "ffmpeg" / "ffmpeg",
        ],
        "ffprobe": [
            tools_dir / "ffmpeg" / ("ffprobe.exe" if is_win else "ffprobe"),
            tools_dir / "ffmpeg" / "ffprobe.exe",
            tools_dir / "ffmpeg" / "ffprobe",
        ],
        "SvtAv1EncApp": [
            tools_dir / "encoders" / ("SvtAv1EncApp.exe" if is_win else "SvtAv1EncApp"),
            tools_dir / "encoders" / "SvtAv1EncApp.exe",
            tools_dir / "encoders" / "SvtAv1EncApp",
        ],
        "exiftool": [
            tools_dir / "exiftool" / ("exiftool.exe" if is_win else "exiftool"),
            tools_dir / "exiftool" / "exiftool.exe",
            tools_dir / "exiftool" / "exiftool",
        ],
        "avifenc": [
            tools_dir / "encoders" / ("avifenc.exe" if is_win else "avifenc"),
            tools_dir / "encoders" / "avifenc.exe",
            tools_dir / "encoders" / "avifenc",
            tools_dir / "avifenc" / "avifenc.exe",
            tools_dir / "avifenc" / "avifenc",
        ],
    }

    candidates = candidate_map.get(tool_name, [])
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK if not is_win else os.R_OK):
            return str(path.resolve())

    # Fallback: check system PATH
    found = shutil.which(tool_name) or shutil.which(f"{tool_name}.exe")
    if found:
        return found

    # If not found, return default relative path
    default_rel = {
        "ffmpeg": "tools/ffmpeg/ffmpeg.exe" if is_win else "tools/ffmpeg/ffmpeg",
        "ffprobe": "tools/ffmpeg/ffprobe.exe" if is_win else "tools/ffmpeg/ffprobe",
        "SvtAv1EncApp": "tools/encoders/SvtAv1EncApp.exe" if is_win else "tools/encoders/SvtAv1EncApp",
        "exiftool": "tools/exiftool/exiftool.exe" if is_win else "tools/exiftool/exiftool",
        "avifenc": "tools/encoders/avifenc.exe" if is_win else "tools/encoders/avifenc",
    }
    return default_rel.get(tool_name, tool_name)


def is_tool_available(tool_name: str) -> bool:
    """Checks whether a tool executable exists and is runnable."""
    path = resolve_tool_path(tool_name)
    if os.path.isabs(path) and os.path.isfile(path):
        return True
    if shutil.which(path) or shutil.which(f"{path}.exe"):
        return True
    return False


class MediaProbe:
    """Helper to inspect media file properties via ffprobe."""
    @staticmethod
    def probe_file(file_path: str) -> Dict[str, Any]:
        ffprobe_bin = resolve_tool_path("ffprobe")
        result = {
            "is_video": False,
            "is_photo": False,
            "width": 0,
            "height": 0,
            "megapixels": 0.0,
            "duration": 0.0,
            "frames": 0,
            "fps": 30.0,
            "audio_streams": 0,
            "size_bytes": 0,
            "color_space_name": "sRGB",
            "primaries_code": 1,
            "transfer_code": 13,
            "matrix_code": 1,
            "profile_desc": "",
        }

        try:
            result["size_bytes"] = os.path.getsize(file_path)
        except Exception:
            pass

        ext = Path(file_path).suffix.lower()
        photo_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".avif"}
        video_exts = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts", ".m4v", ".flv", ".wmv"}

        if ext in photo_exts:
            result["is_photo"] = True
        elif ext in video_exts:
            result["is_video"] = True

        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-show_entries", "stream=index,codec_type,width,height,r_frame_rate,duration,nb_frames,color_space,color_transfer,color_primaries:format=duration",
            "-of", "json",
            file_path,
        ]

        try:
            p = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                **get_subprocess_kwargs()
            )
            if p.returncode == 0:
                data = json.loads(p.stdout)
                streams = data.get("streams", [])
                v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
                a_streams = [s for s in streams if s.get("codec_type") == "audio"]
                result["audio_streams"] = len(a_streams)

                if v_stream:
                    result["width"] = int(v_stream.get("width") or 0)
                    result["height"] = int(v_stream.get("height") or 0)
                    if result["width"] > 0 and result["height"] > 0:
                        result["megapixels"] = round((result["width"] * result["height"]) / 1_000_000.0, 2)

                    # Frame rate
                    fps_str = v_stream.get("r_frame_rate", "30/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        if float(den) > 0:
                            result["fps"] = round(float(num) / float(den), 2)

                    # Frames count
                    if v_stream.get("nb_frames") and v_stream["nb_frames"].isdigit():
                        result["frames"] = int(v_stream["nb_frames"])

                    # Color properties inspection via ffprobe
                    primaries = str(v_stream.get("color_primaries") or "").lower()
                    if "smpte432" in primaries or "p3" in primaries:
                        result["color_space_name"] = "Display P3"
                        result["primaries_code"] = 12
                        result["transfer_code"] = 13
                        result["matrix_code"] = 6
                    elif "bt2020" in primaries:
                        result["color_space_name"] = "BT.2020"
                        result["primaries_code"] = 9
                        result["transfer_code"] = 16
                        result["matrix_code"] = 9

                # Duration
                fmt_duration = data.get("format", {}).get("duration")
                if fmt_duration:
                    try:
                        result["duration"] = float(fmt_duration)
                    except ValueError:
                        pass
                elif v_stream and v_stream.get("duration"):
                    try:
                        result["duration"] = float(v_stream["duration"])
                    except ValueError:
                        pass

                if result["frames"] == 0 and result["duration"] > 0 and result["fps"] > 0:
                    result["frames"] = int(result["duration"] * result["fps"])
        except Exception:
            if result["is_photo"] and result["width"] == 0:
                result["width"] = 1920
                result["height"] = 1080
                result["megapixels"] = 2.07

        return result


class CommandBuilder:
    """Builds command lines for FFmpeg server pipe, SVT-AV1, ExifTool (video), and avifenc."""

    # avifenc natively decodes these input containers.
    AVIFENC_NATIVE_EXTS = {".jpg", ".jpeg", ".png"}

    @staticmethod
    def get_output_path(source_path: str, is_photo: bool) -> str:
        """
        Output location: (source folder)/output/(same filename).ext
        Same base filename as the source, just re-extensioned and routed
        into an "output" subfolder next to the source file.
        """
        src = Path(source_path)
        ext = ".avif" if is_photo else ".mp4"
        output_dir = src.parent / "output"
        dst_name = f"{src.stem}{ext}"
        return str(output_dir / dst_name)

    @staticmethod
    def get_failed_path(source_path: str) -> str:
        """
        Destination for source files that fail the minimum size-reduction
        check: (source folder)/output/(same filename)_failed(original ext)
        """
        src = Path(source_path)
        output_dir = src.parent / "output"
        dst_name = f"{src.stem}_failed{src.suffix}"
        return str(output_dir / dst_name)

    @staticmethod
    def build_video_commands(
        src: str,
        dst: str,
        settings: Dict[str, Any],
        probe: Dict[str, Any],
    ) -> Tuple[List[str], List[str], List[str], List[str], str]:
        """
        Returns (ffmpeg_pipe_cmd, svt_cmd, mux_cmd, exiftool_cmd, temp_ivf_path)
        """
        ffmpeg_bin = resolve_tool_path("ffmpeg")
        svt_bin = resolve_tool_path("SvtAv1EncApp")
        exiftool_bin = resolve_tool_path("exiftool")

        # --- Downscaling Logic & Dimensions Resolution ---
        vf_args = []
        downscale_enabled = settings.get("downscale_gt_1080p", False)
        width = probe.get("width", 0)
        height = probe.get("height", 0)
        
        # Determine max dimension to accurately detect videos larger than 1080p
        max_dim = max(width, height)
        is_downscaled = False

        if downscale_enabled and max_dim > 1080:
            scale_algo = settings.get("scale_filter", "spline36")
            
            # Check orientation after FFmpeg's auto-rotation
            is_vertical = height > width
            
            # Bound the maximum side to 1080 pixels
            if is_vertical:
                w_expr, h_expr = "1080", "-2"
            else:
                w_expr, h_expr = "-2", "1080"

            if scale_algo in ["spline36", "lanczos"]:
                filter_str = f"zscale=w={w_expr}:h={h_expr}:f={scale_algo}"
            else:
                filter_str = f"scale=w={w_expr}:h={h_expr}:flags=spline"

            vf_args = ["-vf", filter_str]
            is_downscaled = True

        # --- Preset Speed Selection (Based on Output Resolution) ---
        # If downscaling was applied, the resulting max dimension will be <= 1080p.
        effective_max_dim = 1080 if is_downscaled else max_dim

        if effective_max_dim <= 1080:
            preset = int(settings.get("preset_le_1080p", 2))
        else:
            preset = int(settings.get("preset_gt_1080p", 4))

        # SVT parameters
        svt_args = [
            svt_bin,
            "-i", "stdin",
            "--input-depth", "10",
            "--preset", str(preset),
            "--tune", str(settings.get("tune", 1)),
        ]

        # CRF slider: if enabled, send --rc 0 --crf <value>
        if settings.get("crf_enabled", False):
            crf_val = float(settings.get("crf", 35.0))
            svt_args.extend(["--rc", "0", "--crf", f"{crf_val:.2f}"])

        # Deblocking loop filter control
        if settings.get("enable_dlf", True):
            svt_args.extend(["--enable-dlf", "2"])

        # Temporal filter ALT-REF frames
        if settings.get("enable_tf", True):
            svt_args.extend(["--enable-tf", "2"])

        # QM-PSNR
        if settings.get("enable_qmpsnr", True):
            svt_args.extend(["--enable-qmpsnr", "1"])

        temp_ivf = str(Path(dst).with_suffix(".temp.ivf"))
        svt_args.extend(["-b", temp_ivf])

        # FFmpeg decoding pipe
        ffmpeg_pipe = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-i", src,
        ] + vf_args + [
            "-strict", "-1",
            "-pix_fmt", "yuv420p10le",
            "-f", "yuv4mpegpipe",
            "-",
        ]

        # Mux to MP4 container with original audio / subtitles
        mux_cmd = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-i", temp_ivf,
            "-i", src,
            "-map", "0:v:0",
            "-map", "1:a?",
            "-map", "1:s?",
            "-c:v", "copy",
            "-c:a", "copy",
            "-c:s", "copy",
            dst,
        ]

        # ExifTool metadata preservation (videos only)
        exiftool_cmd = [
            exiftool_bin,
            "-m",
            "-overwrite_original",
            "-TagsFromFile", src,
            "-all:all",
            "-CommonArgs", dst,
        ]

        return ffmpeg_pipe, svt_args, mux_cmd, exiftool_cmd, temp_ivf

    @staticmethod
    def build_photo_commands(
        src: str,
        dst: str,
        settings: Dict[str, Any],
        probe: Dict[str, Any],
    ) -> Tuple[List[str], Optional[List[str]], str, Dict[str, Any]]:
        """
        Builds the avifenc encode command and an optional FFmpeg pre-conversion
        command (for source formats avifenc can't read directly).

        All photo encoding, metadata preservation (EXIF/ICC/XMP), and gain-map
        handling are performed directly by avifenc in a single pass without ExifTool.

        Returns (avifenc_cmd, convert_cmd_or_None, temp_input_path, gainmap_info)
        """
        avifenc_bin = resolve_tool_path("avifenc")
        ffmpeg_bin = resolve_tool_path("ffmpeg")

        # avifenc natively reads jpg/jpeg/png only. Anything else (webp, bmp,
        # tiff, heic, existing avif, ...) is first converted to a temporary
        # lossless PNG via FFmpeg, which avifenc then encodes.
        src_ext = Path(src).suffix.lower()
        natively_supported = src_ext in CommandBuilder.AVIFENC_NATIVE_EXTS

        convert_cmd: Optional[List[str]] = None
        temp_input = ""
        avifenc_src = src

        if not natively_supported:
            temp_input = str(Path(dst).with_suffix(".temp_src.png"))
            convert_cmd = [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-i", src,
                "-frames:v", "1",
                temp_input,
            ]
            avifenc_src = temp_input

        gain_map_mode = str(settings.get("gain_map_mode", "auto")).lower()
        qgain_map = int(settings.get("qgain_map", 75))

        # --- avifenc settings ---
        qcolor = int(settings.get("qcolor", 50))            # -q,--qcolor   (default 50)
        speed = int(settings.get("speed", 2))                # -s,--speed    (default 2)
        yuv_format = str(settings.get("yuv_format", "444")).lower()  # -y,--yuv (default 444)
        sharpness = int(settings.get("sharpness", 0))         # -a sharpness= (default 0)
        tune = str(settings.get("tune", "iq")).lower()        # -a tune=      (default iq)

        avifenc_args = [
            avifenc_bin,
            "-q", str(qcolor),
            "-s", str(speed),
        ]

        # Only pass -y if it's a specific format; omit -y when set to "auto"
        if yuv_format != "auto":
            avifenc_args.extend(["-y", yuv_format])

        avifenc_args.append("-a")
        avifenc_args.append(f"sharpness={sharpness}")

        if tune != "iq":
            avifenc_args.extend(["-a", f"tune={tune}"])

        # Pass gain map options directly to avifenc
        gain_map_flag = None
        if gain_map_mode == "sdr":
            gain_map_flag = "--ignore-gain-map"
            avifenc_args.append(gain_map_flag)
        else:
            gain_map_flag = "--qgain-map"
            avifenc_args.extend([gain_map_flag, str(qgain_map)])

        avifenc_args.extend([avifenc_src, dst])

        gainmap_info = {
            "gain_map_mode": gain_map_mode,
            "gain_map_flag": gain_map_flag,
            "qgain_map": qgain_map,
        }

        return avifenc_args, convert_cmd, temp_input, gainmap_info


# Minimum fractional size reduction an encoded output must achieve vs. the
# source file to be kept. Anything encoding to 70% or more of the original
# size (i.e. less than a 30% saving), or to a larger file, is considered a
# wasted encode: the output is discarded and the source is preserved instead.
MIN_SIZE_REDUCTION = 0.30


class BatchWorker(QThread):
    """
    QThread worker that processes media jobs sequentially with progress callbacks.
    Executes all subprocesses silently without opening console windows.
    """
    job_started = pyqtSignal(int, str)             # job_idx, filename
    job_progress = pyqtSignal(int, int, str)        # job_idx, percent, status_msg
    job_finished = pyqtSignal(int, bool, str)       # job_idx, success, message
    batch_progress = pyqtSignal(int)                # total_percent
    batch_completed = pyqtSignal(int, int, int)     # total, succeeded, failed
    log_message = pyqtSignal(str)                   # log text

    def __init__(self, jobs: List[Dict[str, Any]], video_settings: Dict[str, Any], photo_settings: Dict[str, Any]):
        super().__init__()
        self.jobs = jobs
        self.video_settings = video_settings
        self.photo_settings = photo_settings
        self._is_cancelled = False
        self._current_processes: List[subprocess.Popen] = []

    def cancel(self):
        """Request immediate batch cancellation."""
        self._is_cancelled = True
        self.log_message.emit("[BatchWorker] Cancellation requested by user.")
        for proc in self._current_processes:
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self):
        total_jobs = len(self.jobs)
        succeeded = 0
        failed = 0

        self.log_message.emit(f"=== Starting AV1 Batch Job ({total_jobs} items) ===")

        for idx, job in enumerate(self.jobs):
            if self._is_cancelled:
                self.log_message.emit(f"Batch cancelled at job #{idx + 1}.")
                break

            src = job["path"]
            filename = Path(src).name
            self.job_started.emit(idx, filename)
            self.job_progress.emit(idx, 5, "Inspecting media...")

            probe = MediaProbe.probe_file(src)
            is_photo = probe["is_photo"]
            dst = CommandBuilder.get_output_path(src, is_photo)

            self.log_message.emit(f"\n[{idx + 1}/{total_jobs}] Processing {filename}")
            self.log_message.emit(f"  Target: {dst}")

            # Make sure (source folder)/output/ exists before anything writes to it
            try:
                Path(dst).parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                failed += 1
                self.job_progress.emit(idx, 100, "Failed")
                self.job_finished.emit(idx, False, f"Could not create output folder: {e}")
                self.log_message.emit(f"  -> ERROR: Could not create output folder: {e}")
                overall_percent = int(((idx + 1) / total_jobs) * 100)
                self.batch_progress.emit(overall_percent)
                continue

            success = False
            error_msg = ""

            try:
                if is_photo:
                    success, error_msg = self._process_photo(idx, src, dst, probe)
                else:
                    success, error_msg = self._process_video(idx, src, dst, probe)
            except Exception as e:
                success = False
                error_msg = str(e)

            if success:
                # --- Size-reduction gate: encoded output must be at least
                # MIN_SIZE_REDUCTION smaller than the source. Otherwise the
                # encode is discarded and the source is kept instead.
                success, error_msg = self._enforce_size_reduction(idx, src, dst, probe)

            if success:
                succeeded += 1
                self.job_progress.emit(idx, 100, "Completed")
                self.job_finished.emit(idx, True, f"Saved: {Path(dst).name}")
                self.log_message.emit(f"  -> SUCCESS: {dst}")
            else:
                failed += 1
                self.job_progress.emit(idx, 100, "Failed")
                self.job_finished.emit(idx, False, error_msg or "Failed")
                self.log_message.emit(f"  -> ERROR: {error_msg}")

            overall_percent = int(((idx + 1) / total_jobs) * 100)
            self.batch_progress.emit(overall_percent)

        self.log_message.emit(f"\n=== Batch Finished: {succeeded} succeeded, {failed} failed ===")
        self.batch_completed.emit(total_jobs, succeeded, failed)

    def _enforce_size_reduction(self, idx: int, src: str, dst: str, probe: Dict[str, Any]) -> Tuple[bool, str]:
        """
        After a successful encode, checks that the output is at least
        MIN_SIZE_REDUCTION smaller than the source. If not (including the
        case where the output ended up larger), the encoded output is
        deleted and the source is moved into the output folder with a
        "_failed" suffix instead.
        """
        src_size = probe.get("size_bytes", 0) or 0
        try:
            dst_size = os.path.getsize(dst)
        except OSError:
            dst_size = 0

        reduction = None
        if src_size > 0 and dst_size > 0:
            reduction = 1.0 - (dst_size / src_size)

        if reduction is not None and reduction >= MIN_SIZE_REDUCTION:
            return True, "Done"

        # Size gate failed (bigger, or under the minimum saving) -> discard
        # the encoded output and move the original into output/ as "_failed".
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except Exception:
                pass

        failed_dst = CommandBuilder.get_failed_path(src)
        try:
            Path(failed_dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(src, failed_dst)
        except Exception as move_err:
            pct_txt = f"{reduction * 100:.1f}%" if reduction is not None else "unknown"
            return False, f"Size reduction only {pct_txt} and failed to move source: {move_err}"

        pct_txt = f"{reduction * 100:.1f}%" if reduction is not None else "unknown"
        self.log_message.emit(
            f"  -> Size reduction only {pct_txt} (< {int(MIN_SIZE_REDUCTION * 100)}%). "
            f"Discarded output, moved source to {failed_dst}"
        )
        return False, f"Insufficient size saving ({pct_txt}); source moved to {Path(failed_dst).name}"

    def _process_video(self, idx: int, src: str, dst: str, probe: Dict[str, Any]) -> Tuple[bool, str]:
        pipe_cmd, svt_cmd, mux_cmd, exif_cmd, temp_ivf = CommandBuilder.build_video_commands(
            src, dst, self.video_settings, probe
        )

        self.log_message.emit("  Step 1: FFmpeg 10-bit pipe -> SvtAv1EncApp...")
        self.log_message.emit("  " + " ".join(pipe_cmd) + " | " + " ".join(svt_cmd))

        self.job_progress.emit(idx, 15, "Encoding 10-bit AV1...")

        kw = get_subprocess_kwargs()

        # Spawn piped processes without filling unread pipe buffers
        p_ffmpeg = subprocess.Popen(
            pipe_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Prevent FFmpeg stderr pipe buffer overflow
            **kw
        )
        p_svt = subprocess.Popen(
            svt_cmd,
            stdin=p_ffmpeg.stdout,
            stdout=subprocess.DEVNULL, # Prevent SVT-AV1 stdout pipe buffer overflow
            stderr=subprocess.PIPE,
            text=True,
            **kw
        )
        p_ffmpeg.stdout.close()  # Allow p_ffmpeg to receive SIGPIPE if p_svt exits

        self._current_processes = [p_ffmpeg, p_svt]

        # Read SVT stderr for progress
        total_frames = probe.get("frames", 0)
        while True:
            if self._is_cancelled:
                p_ffmpeg.kill()
                p_svt.kill()
                if os.path.exists(temp_ivf):
                    os.remove(temp_ivf)
                return False, "Cancelled"

            line = p_svt.stderr.readline() if p_svt.stderr else ""
            if not line and p_svt.poll() is not None:
                break
            if line:
                line_str = line.strip()
                if "frame" in line_str.lower() and total_frames > 0:
                    import re
                    match = re.search(r"frame\s*(\d+)", line_str, re.IGNORECASE)
                    if match:
                        cur_frame = int(match.group(1))
                        pct = min(80, max(15, int(15 + (cur_frame / total_frames) * 65)))
                        self.job_progress.emit(idx, pct, f"Encoding frame {cur_frame}/{total_frames}")

        p_svt.wait()
        p_ffmpeg.wait()
        self._current_processes = []

        if p_svt.returncode != 0:
            err = p_svt.stderr.read() if p_svt.stderr else "SVT-AV1 failed"
            if os.path.exists(temp_ivf):
                os.remove(temp_ivf)
            return False, f"SvtAv1EncApp error (code {p_svt.returncode}): {err[:150]}"

        # Step 2: Mux to MP4
        self.job_progress.emit(idx, 85, "Muxing to MP4 container...")
        self.log_message.emit("  Step 2: Muxing into MP4 container...")
        self.log_message.emit("  " + " ".join(mux_cmd))

        p_mux = subprocess.run(mux_cmd, capture_output=True, text=True, **kw)
        if p_mux.returncode != 0:
            if os.path.exists(temp_ivf):
                os.remove(temp_ivf)
            return False, f"FFmpeg mux error: {p_mux.stderr[:150]}"

        # Remove temporary IVF bitstream
        if os.path.exists(temp_ivf):
            try:
                os.remove(temp_ivf)
            except Exception:
                pass

        # Step 3: ExifTool metadata preservation (videos only)
        self.job_progress.emit(idx, 95, "Copying metadata via ExifTool...")
        self.log_message.emit("  Step 3: Copying metadata via ExifTool...")
        self.log_message.emit("  " + " ".join(exif_cmd))

        p_exif = subprocess.run(exif_cmd, capture_output=True, text=True, **kw)
        exif_out = (p_exif.stdout or "").strip()
        exif_err = (p_exif.stderr or "").strip()

        if p_exif.returncode != 0 or ("Error:" in exif_err) or ("Error:" in exif_out):
            err_msg = exif_err if "Error:" in exif_err else (exif_out or "ExifTool failed")
            self.log_message.emit(f"  [Error] ExifTool error: {err_msg}")
            return False, f"ExifTool error: {err_msg[:150]}"
        elif exif_err:
            self.log_message.emit(f"  [Warning] ExifTool warning: {exif_err}")

        return True, "Done"

    def _process_photo(self, idx: int, src: str, dst: str, probe: Dict[str, Any]) -> Tuple[bool, str]:
        avifenc_cmd, convert_cmd, temp_input, gainmap_info = CommandBuilder.build_photo_commands(
            src, dst, self.photo_settings, probe
        )

        kw = get_subprocess_kwargs()

        # Step 0: Convert source to temporary PNG if avifenc can't read format directly
        if convert_cmd:
            self.job_progress.emit(idx, 15, "Converting source for avifenc...")
            self.log_message.emit("  Step 0: FFmpeg converting source to temporary PNG...")
            self.log_message.emit("  " + " ".join(convert_cmd))

            p_conv = subprocess.run(convert_cmd, capture_output=True, text=True, **kw)
            if p_conv.returncode != 0:
                if temp_input and os.path.exists(temp_input):
                    try:
                        os.remove(temp_input)
                    except Exception:
                        pass
                err = (p_conv.stderr or "").strip()
                return False, f"Source conversion error: {err[:200]}"

        # Step 1: Encode with avifenc (handles image, EXIF/XMP/ICC metadata, and gain maps natively)
        self.job_progress.emit(idx, 50, "Encoding AVIF with avifenc...")
        self.log_message.emit("  Step 1: Single-pass avifenc encoding (metadata & gain map handled natively)...")
        self.log_message.emit("  " + " ".join(avifenc_cmd))

        p_avif = subprocess.run(avifenc_cmd, capture_output=True, text=True, **kw)
        self._current_processes = []

        if p_avif.returncode != 0:
            err = (p_avif.stderr or p_avif.stdout or "").strip()
            gain_map_flag = gainmap_info.get("gain_map_flag")

            # Fallback if --qgain-map or --ignore-gain-map flag is unrecognized by this build
            if gain_map_flag and (
                "unrecognized" in err.lower() or "unknown" in err.lower() or gain_map_flag in err
            ):
                self.log_message.emit(
                    f"  [Warning] avifenc rejected '{gain_map_flag}'. Retrying without gain map flags..."
                )
                fallback_cmd = list(avifenc_cmd)
                if gain_map_flag in fallback_cmd:
                    gi = fallback_cmd.index(gain_map_flag)
                    if gain_map_flag == "--qgain-map":
                        del fallback_cmd[gi:gi + 2]
                    else:
                        del fallback_cmd[gi:gi + 1]
                self.log_message.emit("  " + " ".join(fallback_cmd))
                p_avif = subprocess.run(fallback_cmd, capture_output=True, text=True, **kw)

            if p_avif.returncode != 0:
                if temp_input and os.path.exists(temp_input):
                    try:
                        os.remove(temp_input)
                    except Exception:
                        pass
                err = (p_avif.stderr or p_avif.stdout or "").strip()
                return False, f"avifenc error: {err[:200]}"

        # Clean up temporary conversion file
        if temp_input and os.path.exists(temp_input):
            try:
                os.remove(temp_input)
            except Exception:
                pass

        return True, "Done"