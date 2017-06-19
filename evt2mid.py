import argparse
from collections import deque


def bytesToHexString(data):
    return format(' '.join('{:02X}'.format(c) for c in data))


def getNoteName(noteNumber):
    noteList = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#',
                'G', 'G#', 'A', 'A#', 'B']
    return (noteList[noteNumber % 12] + ('{}({})'.
                                         format((noteNumber // 12) - 1,
                                                noteNumber)))


def getTimeStamp(tick):
    seconds = tick / 1000
    return '{} {}:{:.2f}'.format(tick, int(seconds/60), seconds % 60)


def getSysEx(sysex):
    hexString = ' '.join('{:02X}'.format(c) for c in sysex)
    if sysex[-1] == 0xF7:
        if sysex[:5] == b'\xf0\x43\x70\x70\x78':
            return 'Bar Signal {}/{} ({})'.format(sysex[5], sysex[6], hexString)
    return hexString


def getVLQ(number):
    if number > 0xFFFFFFF:  # TODO: Handle it
        return b'\x0f\xff\xff\xff'
    elif number < 0:
        return b'\x00'
    else:
        ret = bytes([number % 0x80])
        while number > 0x7F:
            number = number // 0x80
            ret = bytes([(number % 0x80) | 0x80]) + ret
        return ret


def genMidiEvent(data):
    global msCount, args, evtDTQueue, midEventQueue
    if args.verbose:
        print('Event Queued: Delta Time {}ms, Data {}'.
              format(msCount['event'], bytesToHexString(data)))
    evtDTQueue.append(msCount['event'])
    midEventQueue.append(data)

    msCount['event'] = 0


def appendMidEventToTruck(dt, data):
    global midTruck, args
    bytesToAppend = getVLQ(dt) + data
    if args.verbose:
        print('Dt = {} ticks, Will write {} to truck'.
              format(dt, bytesToHexString(bytesToAppend)))
    midTruck.extend(bytesToAppend)


def beatSync(ticksms):
    global midTruck, args, truckCount, evtDTQueue, midEventQueue
    global midTicksPerBeat

    if ticksms == 0:
        if args.verbose:
            print('{} Initial Clock (1/24 Beat) Signal'.
                  format(getTimeStamp(msCount['total'])))
    else:
        if args.verbose:
            print(
                ('{} Clock (1/24 Beat) Signal, Length {} ms, '
                    'Tempo {:.2f} BPM').
                format(getTimeStamp(msCount['total']),
                       msCount['beat'],
                       2500/msCount['beat']
                       )
            )

        # To keep msCount['event'] correct:
        genMidiEvent(b'\xff\x51\x03\x07\xa1\x20')

        lastUPB = 1000*ticksms  # microseconds per beat

        # Modify the last speed change event
        assert(midTruck[-6:-3] == b'\xff\x51\x03')
        midTruck[-3:] = lastUPB.to_bytes(3, 'big')

        if args.verbose:
            print('\nAppending Events to Truck:')

        f_dtAccu = 0.0
        dtAccuPre = 0
        while len(evtDTQueue) > 1:
            f_dt = evtDTQueue.popleft() / ticksms * midTicksPerBeat
            f_dtAccu += f_dt
            dt = round(f_dtAccu) - dtAccuPre
            appendMidEventToTruck(dt, midEventQueue.popleft())
            dtAccuPre += dt
            pass

        # Dump last event but ensure all events fill up a whole beat
        lastDTms = evtDTQueue.popleft()
        if args.verbose:
            print(
                'Last dt {:.02f} ticks, corrected to {} ticks to prevent accumulative error'.
                format(lastDTms / ticksms * midTicksPerBeat, midTicksPerBeat - dtAccuPre)
            )
        appendMidEventToTruck(
            midTicksPerBeat - dtAccuPre, midEventQueue.popleft())

        if args.verbose:
            print('')
        pass


parser = argparse.ArgumentParser(description='Convert EVT to MIDI')
parser.add_argument('file_name', type=str, help='Input file name.')
parser.add_argument('-v', '--verbose', help='Print detailed messages',
                    action='store_true')

args = parser.parse_args()

with open(args.file_name, "rb") as fevt:
    if args.verbose:
        print('Processing file {}'.format(args.file_name))
    fevt.seek(256)  # Doesn't know what the first 256 bytes is for
    evtdata = fevt.read()

if evtdata:
    midTicksPerBeat = 480
    # MIDI Track Events, to be written in the .mid file
    # Initialized with an empty speed change
    midTruck = bytearray(b'\x00\xff\x51\x03\x07\xa1\x20')

    msCount = dict(total=0, beat=0, event=0)  # Miliseconds elapsed since xx
    clockCount = 24  # Counting Clock Sync Event

    evtDTQueue = deque([])  # Delta Time Queue in milliseconds
    midEventQueue = deque([])  # MIDI Event Queue

    i = 0
    while i < len(evtdata):
        if evtdata[i] == 0xF3:  # One byte delta time
            i += 1
            for key in msCount:
                msCount[key] += evtdata[i]
#            if args.verbose:
#                print('{} Tick inc'.format(msCount['total']))

        elif evtdata[i] == 0xF4:  # Two bytes delta time
            i += 2
            for key in msCount:
                msCount[key] += (evtdata[i-1] + 128 * evtdata[i])
#            if args.verbose:
#                print('{} Tick inc.'.format(msCount['total']))

        elif evtdata[i] == 0xFE:  # Real Time Message
            i += 1

            if evtdata[i] == 0x78:  # Clock (1/24 Beat)
                if clockCount == 24:  # One Beat
                    clockCount = 1
                    beatSync(msCount['beat'])
                    msCount['beat'] = 0
                    pass
                else:
                    clockCount += 1

            elif evtdata[i] == 0x7A:  # Start
                genMidiEvent(b'\xf0\x02\xfa\xf7')
                if args.verbose:
                    print('{} Start'.format(getTimeStamp(msCount['total'])))

            elif evtdata[i] == 0x7C:  # Stop
                if args.verbose:
                    print('{} Stop'.format(getTimeStamp(msCount['total'])))

            else:
                if args.verbose:
                    print('{} Unknown Real Time Message: {:02X}'.
                          format(getTimeStamp(msCount['total']),
                                 evtdata[i-1:i+1]))

        elif evtdata[i] == 0xF0:  # SysEx
            sysExStart = i
            i += 1
            while evtdata[i] != 0xF7:
                i += 1
            if args.verbose:
                print('{} SysEx: {}'.format(getTimeStamp(msCount['total']),
                                            getSysEx(evtdata[sysExStart:i+1])))
                pass
            genMidiEvent(b'\xf0' +
                         getVLQ(i-sysExStart) +
                         evtdata[sysExStart+1:i+1])

        elif evtdata[i] == 0xF1:  # Debut
            if args.verbose:
                print('{} Debut'.format(getTimeStamp(msCount['total'])))

        elif evtdata[i] == 0xF2:  # Fin
            if args.verbose:
                print('{} Fin'.format(getTimeStamp(msCount['total'])))
            break

        elif (evtdata[i] & 0xF0) != 0xF0:  # MIDI Event
            channelNo = (evtdata[i] & 0x0F) + 1
            eventType = (evtdata[i] & 0xF0)

            if eventType == 0x80:  # Note off
                if args.verbose:
                    print('{} Note off: Channel {}, Note {}'.
                          format(getTimeStamp(msCount['total']),
                                 channelNo,
                                 getNoteName(evtdata[i+1])))
                    pass
                genMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0x90:  # Note on
                if args.verbose:
                    if evtdata[i+2] == 0:  # Note off
                        print('{} Note off: Channel {}, Note {}'.
                              format(getTimeStamp(msCount['total']),
                                     channelNo,
                                     getNoteName(evtdata[i+1])))
                    else:
                        print('{} Note on: Channel {}, Note {}, Vel {}'.
                              format(getTimeStamp(msCount['total']),
                                     channelNo,
                                     getNoteName(evtdata[i+1]),
                                     evtdata[i+2]))
                genMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0xA0:  # Poly aftertouch
                if args.verbose:
                    print('{} Poly AT: Channel {}, Note {}, Pressure {}'.
                          format(getTimeStamp(msCount['total']),
                                 channelNo,
                                 getNoteName(evtdata[i+1]),
                                 evtdata[i+2]))
                genMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0xB0:  # Control Change
                if args.verbose:
                    print('{} CC: Channel {}, Controller {}({:02X}), Value {}'.
                          format(getTimeStamp(msCount['total']),
                                 channelNo, evtdata[i+1],
                                 evtdata[i+1],
                                 evtdata[i+2]))
                genMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0xC0:  # Program Change
                if args.verbose:
                    print('{} PC: Channel {}, Value {}'.
                          format(getTimeStamp(msCount['total']),
                                 channelNo,
                                 evtdata[i+1]))
                genMidiEvent(evtdata[i:i+2])
                i += 1

            elif eventType == 0xD0:  # Channel AT
                if args.verbose:
                    print('{} Channel AT: Channel {}, Value {}'.
                          format(getTimeStamp(msCount['total']),
                                 channelNo,
                                 evtdata[i+1]))
                genMidiEvent(evtdata[i:i+2])
                i += 1

            elif eventType == 0xE0:  # Pitch Wheel
                if args.verbose:
                    print('{} Pitch Wheel: Channel {}, Value {}'.
                          format(getTimeStamp(msCount['total']),
                                 channelNo,
                                 evtdata[i+1] + 256 * evtdata[i+2]))
                genMidiEvent(evtdata[i:i+3])
                i += 2

            else:
                if args.verbose:
                    print('{} Unknown MIDI Event: {:02X}'.
                          format(getTimeStamp(msCount['total']),
                                 evtdata[i]))

        else:
            if args.verbose:
                print('{} Unknown meta event: {:02X}'.
                      format(getTimeStamp(msCount['total']),
                             evtdata[i]))

        i += 1

    midFileName = args.file_name + '.mid'

    with open(midFileName, "wb") as fmid:
        if args.verbose:
            print('Saving file {}'.format(midFileName))
        midHeader = (b'MThd' +
                     b'\x00\x00\x00\x06' +
                     b'\x00\x00' +
                     b'\x00\x01' +
                     midTicksPerBeat.to_bytes(2, 'big'))
        midTruck = (
            b'MTrk' +
            len(midTruck).to_bytes(4, 'big') +
            midTruck +
            b'\x00\xff\x2f\x00'  # End of track event
        )
        fmid.write(midHeader)
        fmid.write(midTruck)
