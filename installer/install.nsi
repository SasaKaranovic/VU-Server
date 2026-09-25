; INSTALLEROUTPUT -> Output filepath
; DIRDIST -> `/dist` directory path
; DIRSOURCE -> Repository path
; makensis \DINSTALLEROUTPUT="${{ github.workspace }}/Artifacts/VU1-Installer.exe" \DDIRDIST="${{ github.workspace }}\dist" \DDIRSOURCE="${{ github.workspace }}" installer\install.nsi

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

# Add/Remove Programs registry key
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${COMPANYNAME} ${APPNAME}"

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

  File /r "${DIRDIST}\*"
  File "${DIRSOURCE}\installer\inc\icon.ico"

  # Start Menu
  createDirectory "$SMPROGRAMS\${COMPANYNAME}"
  createShortCut "$SMPROGRAMS\${COMPANYNAME}\${APPNAME}.lnk" "$INSTDIR\${MAINEXE}" "" "$INSTDIR\icon.ico"

  # Registry information for add/remove programs
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "${COMPANYNAME} - ${APPNAME} - ${DESCRIPTION}"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
  WriteRegStr HKLM "${UNINSTKEY}" "QuietUninstallString" "$\"$INSTDIR\uninstall.exe$\" /S"
  WriteRegStr HKLM "${UNINSTKEY}" "InstallLocation" "$\"$INSTDIR$\""
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon" "$\"$INSTDIR\icon.ico$\""
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "$\"${COMPANYNAME}$\""
  WriteRegStr HKLM "${UNINSTKEY}" "HelpLink" "$\"${HELPURL}$\""
  WriteRegStr HKLM "${UNINSTKEY}" "URLUpdateInfo" "$\"${UPDATEURL}$\""
  WriteRegStr HKLM "${UNINSTKEY}" "URLInfoAbout" "$\"${ABOUTURL}$\""
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "$\"${VERSIONMAJOR}.${VERSIONMINOR}.${VERSIONBUILD}$\""
  WriteRegDWORD HKLM "${UNINSTKEY}" "VersionMajor" ${VERSIONMAJOR}
  WriteRegDWORD HKLM "${UNINSTKEY}" "VersionMinor" ${VERSIONMINOR}
  # There is no option for modifying or repairing the install
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1
  # Set the INSTALLSIZE constant (!defined at the top of this script) so Add/Remove Programs can accurately report the size
  WriteRegDWORD HKLM "${UNINSTKEY}" "EstimatedSize" ${INSTALLSIZE}

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

  RMDir /r "$INSTDIR"

  Delete "$SMPROGRAMS\${COMPANYNAME}\${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${COMPANYNAME}"

  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "VUServer"
  DeleteRegKey HKLM "${UNINSTKEY}"

SectionEnd
