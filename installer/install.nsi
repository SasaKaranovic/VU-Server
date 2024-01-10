; INSTALLEROUTPUT -> Output filepath
; DIRDIST -> `/dist` directory path
; DIRSOURCE -> Repository path
; makensis \DINSTALLEROUTPUT="${{ github.workspace }}/Artifacts/VU1-Installer.exe" \DDIRDIST="${{ github.workspace }}\dist" \DDIRSOURCE="${{ github.workspace }}" installer\install.nsi

# If you change the names "app.exe", "logo.ico", or "license.rtf" you should do a search and replace - they
# show up in a few places.
# All the other settings can be tweaked by editing the !defines at the top of this script
!define APPNAME "VUDials Server"
!define COMPANYNAME "KaranovicResearch"
!define DESCRIPTION "Server application required for VU Dials operation"
# These three must be integers
!define VERSIONMAJOR {{VU_VERSION_MAJOR}}
!define VERSIONMINOR {{VU_VERSION_MINOR}}
!define VERSIONBUILD {{VU_VERSION_BUILD}}
# These will be displayed by the "Click here for support information" link in "Add/Remove Programs"
# It is possible to use "mailto:" links in here to open the email client
!define HELPURL "http://forum.vudials.com" # "Support Information" link
!define UPDATEURL "http://forum.vudials.com" # "Product Updates" link
!define ABOUTURL "http://forum.vudials.com" # "Publisher" link
# This is the size (in kB) of all the files copied into "Program Files"
!define INSTALLSIZE 74209

# Executable
!define MAINEXE VUServer.exe

;--------------------------------
;Include Modern UI

  !include "MUI2.nsh"

;--------------------------------
;General

  ;Name and file
  Name "VUDials"
  Icon "inc\icon.ico"
  OutFile "${INSTALLEROUTPUT}"
  Unicode True

  ;Default installation folder
  InstallDir "$PROGRAMFILES\KaranovicResearch\VUDials"

  ;Get installation folder from registry if available
  InstallDirRegKey HKCU "Software\VUDials" ""

  ;Request application privileges for Windows Vista
  RequestExecutionLevel admin

;--------------------------------
;Interface Settings

  !define MUI_ABORTWARNING

;--------------------------------
;Pages

  !insertmacro MUI_PAGE_LICENSE "${NSISDIR}\Docs\Modern UI\License.txt"
  !insertmacro MUI_PAGE_COMPONENTS
  !insertmacro MUI_PAGE_DIRECTORY
  !insertmacro MUI_PAGE_INSTFILES

  !insertmacro MUI_UNPAGE_CONFIRM
  !insertmacro MUI_UNPAGE_INSTFILES
  !insertmacro MUI_PAGE_FINISH

;--------------------------------
;Languages

  !insertmacro MUI_LANGUAGE "English"

;--------------------------------
;Installer Sections

Section "VUDials Server" VUDSERVER

  SetOutPath "$INSTDIR"

  ;ADD YOUR OWN FILES HERE...
  File /r "${DIRDIST}\*"
  File "${DIRSOURCE}\installer\inc\icon.ico"

  # Start Menu
  createDirectory "$SMPROGRAMS\${COMPANYNAME}"
  createShortCut "$SMPROGRAMS\${COMPANYNAME}\${APPNAME}.lnk" "$INSTDIR\${MAINEXE}" "" "$INSTDIR\icon.ico"

  ; Run server on Windows start
  ;WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APPNAME}" "$INSTDIR\${MAINEXE}"

  ;Store installation folder
  ;WriteRegStr HKCU "Software\VUDials\install_path" "" $INSTDIR

  # Registry information for add/remove programs
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "DisplayName" "${COMPANYNAME} - ${APPNAME} - ${DESCRIPTION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "QuietUninstallString" "$\"$INSTDIR\uninstall.exe$\" /S"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "InstallLocation" "$\"$INSTDIR$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "DisplayIcon" "$\"$INSTDIR\icon.ico$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "Publisher" "$\"${COMPANYNAME}$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "HelpLink" "$\"${HELPURL}$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "URLUpdateInfo" "$\"${UPDATEURL}$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "URLInfoAbout" "$\"${ABOUTURL}$\""
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "DisplayVersion" "$\"${VERSIONMAJOR}.${VERSIONMINOR}.${VERSIONBUILD}$\""
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "VersionMajor" ${VERSIONMAJOR}
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "VersionMinor" ${VERSIONMINOR}
  # There is no option for modifying or repairing the install
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "NoRepair" 1
  # Set the INSTALLSIZE constant (!defined at the top of this script) so Add/Remove Programs can accurately report the size
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}" "EstimatedSize" ${INSTALLSIZE}

  ;Create uninstaller
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Add VU1 to Windows start
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "VUServer" '"$InstDir\VUServer.exe"'

  ; Run the VU server
  ExecShell "" "$InstDir\VUServer.exe"

SectionEnd

;--------------------------------
;Descriptions

  ;Language strings
  LangString DESC_VUServer ${LANG_ENGLISH} "VU Dials API server."

  ;Assign language strings to sections
  !insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${VUDSERVER} $(DESC_VUServer)
  !insertmacro MUI_FUNCTION_DESCRIPTION_END

;--------------------------------
;Uninstaller Section

Section "Uninstall"

  ; Install dir
  Delete "$INSTDIR\*.*"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$smprograms\VUDials\"
  RMDir /r "$INSTDIR"

  ; Remove windows start
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "VUServer"

SectionEnd
