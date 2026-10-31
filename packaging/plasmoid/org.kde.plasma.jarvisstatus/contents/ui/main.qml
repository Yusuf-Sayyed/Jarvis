import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components 3.0 as PlasmaComponents

PlasmoidItem {
    id: root

    preferredRepresentation: fullRepresentation
    compactRepresentation: fullRepresentation

    property string currentStatus: "STANDBY"

    function fetchStatus() {
        var xhr = new XMLHttpRequest();
        // Read directly from file in XDG_RUNTIME_DIR
        var runtimeUrl = "file:///run/user/1000/jarvis/status.json";
        xhr.open("GET", runtimeUrl, true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status === 200 || xhr.status === 0) {
                    try {
                        var obj = JSON.parse(xhr.responseText);
                        if (obj && obj.status) {
                            var s = obj.status.toUpperCase();
                            if (s === "STANDBY" || s === "LISTENING" || s === "THINKING" || s === "SPEAKING" || s === "ERROR") {
                                root.currentStatus = s;
                                return;
                            }
                        }
                    } catch (e) {
                        // ignore parse errors during atomic writes
                    }
                }
                root.currentStatus = "STANDBY";
            }
        };
        xhr.send();
    }

    Timer {
        id: statusTimer
        interval: 500
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.fetchStatus()
    }

    fullRepresentation: Item {
        id: container
        Layout.fillHeight: true
        implicitWidth: statusText.implicitWidth + 8
        implicitHeight: statusText.implicitHeight

        PlasmaComponents.Label {
            id: statusText
            anchors.centerIn: parent
            text: root.currentStatus
            font.bold: true
            font.pixelSize: 11
            font.family: "Monospace"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: {
                switch (root.currentStatus) {
                    case "LISTENING": return "#2ecc71"; // Vivid green
                    case "THINKING":  return "#3498db"; // Vivid blue / cyan
                    case "SPEAKING":  return "#f39c12"; // Warm gold / orange
                    case "ERROR":     return "#e74c3c"; // Red
                    default:          return "#95a5a6"; // Muted standby
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                root.fetchStatus();
            }
        }
    }
}
