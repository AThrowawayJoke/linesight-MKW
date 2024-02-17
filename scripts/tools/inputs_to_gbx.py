import argparse
import psutil
import time
import os
import signal
import shutil
from config_files import misc

from trackmania_rl import map_loader
from trackmania_rl.tmi_interaction.tminterface2 import MessageType, TMInterface

if misc.is_linux:
    from xdo import Xdo
else:
    import win32.lib.win32con as win32con
    import win32com.client
    import win32gui

Run_Speed = 20
Timeout = 2

def get_tm_window_id(tm_process_id):
    if misc.is_linux:
        tm_window_id = Xdo().search_windows(winname=b"Track", pid=tm_process_id)
    else:
        def get_hwnds_for_pid(pid):
            def callback(hwnd, hwnds):
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)

                if found_pid == pid:
                    hwnds.append(hwnd)
                return True

            hwnds = []
            win32gui.EnumWindows(callback, hwnds)
            return hwnds

        while True:
            for hwnd in get_hwnds_for_pid(tm_process_id):
                if win32gui.GetWindowText(hwnd).startswith("Track"):
                    tm_window_id = hwnd
    return tm_window_id

def is_game_running(tm_process_id):
    return (tm_process_id is not None) and (tm_process_id in (p.pid for p in psutil.process_iter()))

def launch_game(TMI_Port):
    tm_process_id = None

    if misc.is_linux:
        pid_before = [proc.pid for proc in psutil.process_iter() if proc.name().startswith("TmForever")]
        print(misc.linux_launch_game_path)
        os.system(misc.linux_launch_game_path + " " + str(TMI_Port))
        pid_after = [proc.pid for proc in psutil.process_iter() if proc.name().startswith("TmForever")]
        tmi_pid_candidates = set(pid_after) - set(pid_before)
        assert len(tmi_pid_candidates) == 1
        tm_process_id = list(tmi_pid_candidates)[0]
    else:
        tmi_process_id = int(
            subprocess.check_output(
                'powershell -executionPolicy bypass -command "& {$process = start-process $args[0] -passthru -argumentList \'/configstring=\\"set custom_port '
                + str(TMI_Port)
                + '\\"\'; echo exit $process.id}" TMInterface.lnk'
            )
            .decode()
            .split("\r\n")[1]
        )

        print(f"Found {tmi_process_id=}")

        tm_processes = list(
            filter(
                lambda s: s.startswith("TmForever"),
                subprocess.check_output("wmic process get Caption,ParentProcessId,ProcessId").decode().split("\r\n"),
            )
        )
        for process in tm_processes:
            name, parent_id, process_id = process.split()
            parent_id = int(parent_id)
            process_id = int(process_id)
            if parent_id == tmi_process_id:
                tm_process_id = process_id

    assert tm_process_id is not None
    print(f"Found Trackmania process id: {tm_process_id=}")
    while not is_game_running(tm_process_id):
        time.sleep(0)

    return tm_process_id, get_tm_window_id(tm_process_id)

def close_game(tm_process_id):
    if misc.is_linux:
        os.system("kill -9 " + str(tm_process_id))
    else:
        os.system(f"taskkill /PID {tm_process_id} /f")
    while is_game_running(tm_process_id):
        time.sleep(0)

def request_map(iface, map_path):
    map_loader.hide_PR_replay(map_path,True)
    iface.execute_command(f"map \"{map_path}\"")

def signal_handler(tm_process_id):
    print(1)
    close_game(tm_process_id)
    exit()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs_dir", "-i", type=str, required=True)
    parser.add_argument("--map_path", "-m", type=str, required=True)
    parser.add_argument("--tmi_port", "-p", type=int, default=8677)
    args = parser.parse_args()
    iface = TMInterface(args.tmi_port)
    inputs_folder = args.inputs_dir if args.inputs_dir[0] in ['/','\\'] else os.path.join(os.getcwd(),args.inputs_dir)
    inputs_foldername = inputs_folder[inputs_folder.rfind('/' if misc.is_linux else '\\')+1:]
    outputs_folder = os.path.join(inputs_folder[:inputs_folder.rfind('/' if misc.is_linux else '\\')],inputs_foldername + "_out")
    print("Inputs folder",inputs_folder)
    print("Outputs folder",outputs_folder)
    if not os.path.isdir(outputs_folder):
        os.mkdir(outputs_folder)
    input_files = [f for f in os.listdir(args.inputs_dir) if os.path.isfile(os.path.join(args.inputs_dir, f))]
    PR_Replay_Filename, PR_Replay_Path = map_loader.PR_replay_from_map_path(args.map_path)

    tm_process_id, _ = launch_game(args.tmi_port)
    signal.signal(signal.SIGINT, lambda:signal_handler(tm_process_id))

    if not iface.registered:
        while True:
            try:
                iface.register(2)
                break
            except ConnectionRefusedError as e:
                print(e)

    def replay_file_ready():
        return os.path.isfile(PR_Replay_Path / PR_Replay_Filename)
    give_up_signal_has_been_sent = False
    expecting_replay_file = False
    current_input_idx = 0
    Start_Time = time.perf_counter()
    while True:
        msgtype = iface._read_int32()
        if expecting_replay_file and replay_file_ready():
            output_filename = input_files[current_input_idx][:input_files[current_input_idx].rfind('.')] + '.Replay.Gbx'
            shutil.move(PR_Replay_Path / PR_Replay_Filename, os.path.join(outputs_folder,output_filename))
            current_input_idx += 1
            expecting_replay_file = False
            give_up_signal_has_been_sent = False
            files_per_second = current_input_idx / (time.perf_counter()-Start_Time)
            print(current_input_idx,"/",len(input_files),"files in",time.perf_counter()-Start_Time,"s. ETA",(len(input_files)-current_input_idx)/files_per_second,"s")
        if msgtype == int(MessageType.SC_RUN_STEP_SYNC):
            _time = iface._read_int32()
            if not give_up_signal_has_been_sent:
                iface.execute_command("load " + input_files[current_input_idx])
                iface.give_up()
                give_up_signal_has_been_sent = True
            iface._respond_to_call(msgtype)
        elif msgtype == int(MessageType.SC_CHECKPOINT_COUNT_CHANGED_SYNC):
            current = iface._read_int32()
            target = iface._read_int32()
            if current == target:#Run finished
                expecting_replay_file = True
                request_map(iface,args.map_path)
                #iface.prevent_simulation_finish()
            iface._respond_to_call(msgtype)
        elif msgtype == int(MessageType.SC_LAP_COUNT_CHANGED_SYNC):
            iface._read_int32()
            iface._read_int32()
            iface._respond_to_call(msgtype)
        elif msgtype == int(MessageType.SC_REQUESTED_FRAME_SYNC):
            iface._respond_to_call(msgtype)
        elif msgtype == int(MessageType.C_SHUTDOWN):
            iface.close()
        elif msgtype == int(MessageType.SC_ON_CONNECT_SYNC):
            iface.execute_command(f"set autologin {misc.username}")
            iface.execute_command(f"set auto_reload_plugins false")
            iface.execute_command("toggle_console")
            iface.execute_command("set scripts_folder " + inputs_folder)
            iface.set_timeout(Timeout*1000)
            iface.set_speed(Run_Speed)
            iface.execute_command(f"set countdown_speed "+str(Run_Speed))
            iface.execute_command(f"set temp_save_states_collect false")
            iface.execute_command(f"set skip_map_load_screens true")
            map_loader.hide_PR_replay(args.map_path,True)
            request_map(iface,args.map_path)
            iface._respond_to_call(msgtype)
        else:
            pass


if __name__ == "__main__":
    main()