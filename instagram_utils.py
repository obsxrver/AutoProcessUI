import os
from pathlib import Path
from typing import List, Optional, Tuple
import instaloader
import cv2
import time
import re

# A realistic user-agent can help avoid Instagram's bot detection
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"


class InstagramAuthError(Exception):
    """Custom exception for Instagram authentication issues"""
    def __init__(self, message: str, error_type: str = "general", challenge_url: str = None):
        self.message = message
        self.error_type = error_type
        self.challenge_url = challenge_url
        super().__init__(self.message)


def _parse_challenge_url(error_message: str) -> Optional[str]:
    """Extract challenge URL from Instagram error message"""
    # Look for challenge URL pattern in error message
    challenge_pattern = r'/challenge/action/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/'
    match = re.search(challenge_pattern, error_message)
    if match:
        return f"https://www.instagram.com{match.group()}"
    return None


def _login(username: str, password: str | None, remember: bool, 
          session_dir: str = "instagram_sessions") -> instaloader.Instaloader:
    """Enhanced Instagram login with better error handling."""
    Path(session_dir).mkdir(exist_ok=True)
    session_file = Path(session_dir) / f"{username}.session"
    
    L = instaloader.Instaloader(
        user_agent=USER_AGENT,
        download_video_thumbnails=False,
        download_videos=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        # More conservative settings to avoid detection
        sleep=True,
        quiet=True
    )
    
    # Try to load existing session first
    if session_file.exists():
        try:
            L.load_session_from_file(username, str(session_file))
            print(f"✓ Loaded existing session for {username}")
            return L
        except Exception as e:
            print(f"⚠️ Failed to load session: {e}")
            # Remove corrupted session file
            try:
                session_file.unlink()
            except:
                pass
    
    # Require password for new login
    if password is None:
        raise InstagramAuthError(
            "Password required for new login. If you have an existing session, ensure the session file is valid.",
            "no_password"
        )
    
    try:
        # Attempt login
        print(f"🔑 Attempting login for {username}...")
        L.login(username, password)
        
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        # The user has indicated 2FA is not desired.
        raise InstagramAuthError(
            "Two-factor authentication is required by Instagram, but this feature is not supported in the current setup.",
            "2fa_unsupported"
        )
    
    except instaloader.exceptions.BadCredentialsException:
        raise InstagramAuthError(
            "Invalid username or password. Please check your credentials.",
            "bad_credentials"
        )
    
    except instaloader.exceptions.ConnectionException as e:
        error_str = str(e)
        
        # Check for various Instagram challenges/errors
        if "checkpoint" in error_str.lower() or "challenge" in error_str.lower():
            challenge_url = _parse_challenge_url(error_str)
            raise InstagramAuthError(
                f"Instagram security checkpoint required. You need to complete verification in your browser.\n"
                f"Please visit: {challenge_url if challenge_url else 'Instagram.com'}\n"
                f"After completing the challenge, try again or create a session file manually.",
                "checkpoint_required",
                challenge_url
            )
        
        elif "rate limit" in error_str.lower() or "too many" in error_str.lower():
            raise InstagramAuthError(
                "Rate limit exceeded. Please wait a few hours before trying again.",
                "rate_limited"
            )
        
        elif "suspicious" in error_str.lower():
            raise InstagramAuthError(
                "Login blocked due to suspicious activity. Please log in manually through a browser first.",
                "suspicious_activity"
            )
        
        else:
            raise InstagramAuthError(
                f"Connection error: {error_str}",
                "connection_error"
            )
    
    except Exception as e:
        error_str = str(e)
        
        # Check for checkpoint in any other exception
        if "checkpoint" in error_str.lower() or "/challenge/" in error_str:
            challenge_url = _parse_challenge_url(error_str)
            raise InstagramAuthError(
                f"Instagram requires additional verification. Please complete the challenge in your browser:\n"
                f"{challenge_url if challenge_url else 'Visit Instagram.com and log in manually'}\n"
                f"After verification, you can create a session file or try again.",
                "verification_required",
                challenge_url
            )
        
        raise InstagramAuthError(
            f"Login failed: {error_str}",
            "unknown_error"
        )
    
    print(f"✓ Login successful for {username}")
    
    # Save session if requested
    if remember:
        try:
            L.save_session_to_file(str(session_file))
            print(f"✓ Session saved for {username}")
        except Exception as e:
            print(f"⚠️ Failed to save session: {e}")
    
    return L


def create_session_manually(username: str, session_dir: str = "instagram_sessions") -> str:
    """Instructions for manually creating a session file"""
    Path(session_dir).mkdir(exist_ok=True)
    session_file = Path(session_dir) / f"{username}.session"
    
    instructions = f"""
To create a session file manually:

1. Install instaloader: pip install instaloader
2. Run this command in terminal:
   instaloader --login {username} --sessionfile {session_file}
3. Follow the prompts to complete login.
4. The session file will be saved and can be used by this application

Alternative method:
1. Open a Python console where instaloader is installed
2. Run:
   import instaloader
   L = instaloader.Instaloader()
   L.login("{username}", "your_password")
   L.save_session_to_file("{session_file}")

Session file location: {session_file}
"""
    return instructions


def fetch_profile_images(profile: str, login_user: str, password: str | None = None,
                          remember: bool = False, max_images: int = 20,
                          output_dir: str = "instagram_downloads") -> Tuple[List[str], dict]:
    """
    Fetch images from Instagram profile with enhanced error handling
    
    Returns:
        Tuple of (downloaded_paths, info_dict)
        info_dict contains status information and error details
    """
    info = {
        "status": "success",
        "error_type": None,
        "error_message": None,
        "challenge_url": None,
        "manual_instructions": None
    }
    
    try:
        L = _login(login_user, password, remember)
        
        try:
            profile_obj = instaloader.Profile.from_username(L.context, profile)
        except instaloader.exceptions.ProfileNotExistsException:
            info.update({
                "status": "error",
                "error_type": "profile_not_found",
                "error_message": f"Profile '{profile}' not found or is private."
            })
            return [], info
        except Exception as e:
            info.update({
                "status": "error", 
                "error_type": "profile_access_error",
                "error_message": f"Cannot access profile '{profile}': {str(e)}"
            })
            return [], info
        
        Path(output_dir).mkdir(exist_ok=True)
        paths: List[str] = []
        count = 0
        downloaded = 0
        
        print(f"📥 Fetching up to {max_images} images from @{profile}...")
        
        try:
            for post in profile_obj.get_posts():
                if count >= max_images:
                    break
                
                if post.typename != "GraphImage":
                    continue
                
                try:
                    fname = Path(output_dir) / f"{post.date_utc.strftime('%Y%m%d_%H%M%S')}_{post.mediaid}.jpg"
                    
                    if L.download_pic(str(fname), post.url, post.date_utc):
                        paths.append(str(fname))
                        downloaded += 1
                        print(f"✓ Downloaded {downloaded}/{max_images}: {fname.name}")
                    
                    count += 1
                    
                    # Add small delay to avoid rate limiting
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"⚠️ Failed to download post {post.mediaid}: {e}")
                    continue
        
        except Exception as e:
            info.update({
                "status": "partial_success",
                "error_type": "download_error", 
                "error_message": f"Error during download: {str(e)}. Downloaded {len(paths)} images before error."
            })
        
        print(f"✓ Successfully downloaded {len(paths)} images from @{profile}")
        return paths, info
        
    except InstagramAuthError as e:
        info.update({
            "status": "error",
            "error_type": e.error_type,
            "error_message": e.message,
            "challenge_url": e.challenge_url
        })
        
        # Add manual instructions for certain error types
        if e.error_type in ["checkpoint_required", "verification_required"]:
            info["manual_instructions"] = create_session_manually(login_user)
        
        return [], info
    
    except Exception as e:
        info.update({
            "status": "error",
            "error_type": "unexpected_error",
            "error_message": f"Unexpected error: {str(e)}"
        })
        return [], info


def filter_single_human_images(image_paths: List[str]) -> List[str]:
    """Filter images to keep only those with exactly one human face"""
    if not image_paths:
        return []
    
    keep: List[str] = []
    
    try:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        
        print(f"🔍 Filtering {len(image_paths)} images for single human faces...")
        
        for i, p in enumerate(image_paths):
            try:
                img = cv2.imread(p)
                if img is None:
                    print(f"⚠️ Could not read image: {Path(p).name}")
                    continue
                
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
                
                if len(faces) == 1:
                    keep.append(p)
                    print(f"✓ Kept {len(keep)}/{i+1}: {Path(p).name} (1 face detected)")
                else:
                    print(f"⚠️ Skipped {Path(p).name} ({len(faces)} faces detected)")
                    
            except Exception as e:
                print(f"⚠️ Error processing {Path(p).name}: {e}")
                continue
        
        print(f"✓ Face filtering complete: {len(keep)}/{len(image_paths)} images kept")
        return keep
        
    except Exception as e:
        print(f"⚠️ Face detection failed: {e}")
        print("Returning all images without filtering")
        return image_paths
