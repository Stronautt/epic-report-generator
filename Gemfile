# Ruby dependencies for the Mac App Store distribution channel (fastlane only).
#
# Pinned for reproducible CI installs (`bundle install`); the MAS upload job uses
# `bundle exec fastlane …`. The Developer-ID `.dmg` channel does not need this.
#
# Floor is 2.228.0+ (here: 2.236.1): the `mac profile` lane creates a macOS App
# Store provisioning profile via `sigh`, and fastlane <= 2.227.2 sends an unknown
# `template_name` attribute that Apple's ASC API now rejects ("'templateName' is
# not an attribute on the resource 'profiles'"). Fixed by fastlane PR #29591
# (merged 2025-06-09). Do not pin below 2.228.0 or the profile lane breaks.
#
# Also avoid 2.236.0 specifically: it double-decoded base64 .p8 key content
# (breaks `app_store_connect_api_key(is_key_content_base64: true)`); reverted in
# 2.236.1 (#30066). Ruby floor for this range is >= 3.0; CI runs 3.3.
source "https://rubygems.org"

gem "fastlane", "2.236.1"
