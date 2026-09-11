# DiamondCrew Interactive / Server Controller 1.2.1

Fix the opt-in Staff SSO installer when root uses umask 077. Runtime directories
and files receive explicit permissions, and cockpit.conf original mode is saved
for uninstall/rollback. Existing unrelated parent directories are not silently
made more permissive. Configuration and credentials remain private.

This corrects the 1.2.0 installation failure where the service could not traverse
the generated dci-sso directory and atomic configuration writes lost mode bits.
Staff SSO verification, Cockpit bearer/PAM, Unix mapping and sudo rules are unchanged.
See docs/test-results.md for native authentication evidence, installer regression
results and remaining browser/password/sudo end-to-end boundaries.
