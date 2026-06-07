@echo off
mklink /d D:\vss_temp "\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopy13"
if exist D:\vss_temp\claude-apace\my-itr-mvp\README.md (
    copy "D:\vss_temp\claude-apace\my-itr-mvp\README.md" "D:\claude-apace\my-itr-mvp\README-ORIGINAL.md" /Y
    echo COPIED
) else (
    echo NOT_FOUND
)
rd D:\vss_temp
