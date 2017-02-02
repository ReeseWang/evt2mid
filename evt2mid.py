import argparse


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


def writeMidiEvent(data):
    global tickCount
    global midTruck
    global i
    global evtdata
    global args
    bytesToAppend = getVLQ(tickCount['event']) + data
    if args.verbose:
        print('Writing {} to MIDI File'.
              format(' '.
                     join('{:02X}'.
                          format(c) for c in bytesToAppend)))
    midTruck = midTruck + bytesToAppend
    tickCount['event'] = 0


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
    midBeatsPerMinute = 125  # EVT file fixed at 2500 ticks per minute
    midTicksPerBeat = 480  #
    midTruck = b''  # MIDI Track Events, to be written in the .mid file

    tickCount = dict(total=0, beat=0, event=0)  # Ticks elapsed since xx

    i = 0
    while i < len(evtdata):
        if evtdata[i] == 0xF3:  # One byte delta time
            i += 1
            for key in tickCount:
                tickCount[key] += evtdata[i]
#            if args.verbose:
#                print('{} Tick inc'.format(tickCount['total']))

        elif evtdata[i] == 0xF4:  # Two bytes delta time
            i += 2
            for key in tickCount:
                tickCount[key] += (evtdata[i-1] + 128 * evtdata[i])
#            if args.verbose:
#                print('{} Tick inc.'.format(tickCount['total']))

        elif evtdata[i] == 0xFE:  # Real Time Message
            i += 1

            if evtdata[i] == 0x78:  # 1/24 Beat
                if args.verbose:
                    if tickCount['beat'] == 0:
                        print('{} Initial Beat Signal'.
                              format(getTimeStamp(tickCount['total'])))
                    else:
                        print(
                            ('{} 1/24 Beat Signal, Length {} ticks, '
                             'Tempo {:.2f} BPM').
                            format(getTimeStamp(tickCount['total']),
                                   tickCount['beat'],
                                   2500/tickCount['beat']
                                   )
                        )
                tickCount['beat'] = 0

            elif evtdata[i] == 0x7A:  # Start
                if args.verbose:
                    print('{} Start'.format(getTimeStamp(tickCount['total'])))
                pass

            elif evtdata[i] == 0x7C:  # Stop
                if args.verbose:
                    print('{} Stop'.format(getTimeStamp(tickCount['total'])))
                pass

            else:
                if args.verbose:
                    print('{} Unknown Real Time Message: {:02X}'.
                          format(getTimeStamp(tickCount['total']),
                                 evtdata[i-1:i+1]))
                pass

        elif evtdata[i] == 0xF0:  # SysEx
            sysExStart = i
            i += 1
            while evtdata[i] != 0xF7:
                i += 1
            if args.verbose:
                print('{} SysEx: {}'.format(getTimeStamp(tickCount['total']),
                                            getSysEx(evtdata[sysExStart:i+1])))
            writeMidiEvent(b'\xf0' +
                           getVLQ(i-sysExStart) +
                           evtdata[sysExStart+1:i+1])

        elif evtdata[i] == 0xF1:  # Debut
            if args.verbose:
                print('{} Debut'.format(getTimeStamp(tickCount['total'])))

        elif evtdata[i] == 0xF2:  # Fin
            if args.verbose:
                print('{} Fin'.format(getTimeStamp(tickCount['total'])))
            break

        elif (evtdata[i] & 0xF0) != 0xF0:  # MIDI Event
            channelNo = (evtdata[i] & 0x0F) + 1
            eventType = (evtdata[i] & 0xF0)

            if eventType == 0x80:  # Note off
                if args.verbose:
                    print('{} Note off: Channel {}, Note {}'.
                          format(getTimeStamp(tickCount['total']),
                                 channelNo,
                                 getNoteName(evtdata[i+1])))
                writeMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0x90:  # Note on
                if args.verbose:
                    if evtdata[i+2] == 0:  # Note off
                        print('{} Note off: Channel {}, Note {}'.
                              format(getTimeStamp(tickCount['total']),
                                     channelNo,
                                     getNoteName(evtdata[i+1])))
                    else:
                        print('{} Note on: Channel {}, Note {}, Vel {}'.
                              format(getTimeStamp(tickCount['total']),
                                     channelNo,
                                     getNoteName(evtdata[i+1]),
                                     evtdata[i+2]))
                writeMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0xA0:  # Poly aftertouch
                if args.verbose:
                    print('{} Poly AT: Channel {}, Note {}, Pressure {}'.
                          format(getTimeStamp(tickCount['total']),
                                 channelNo,
                                 getNoteName(evtdata[i+1]),
                                 evtdata[i+2]))
                writeMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0xB0:  # Control Change
                if args.verbose:
                    print('{} CC: Channel {}, Controller {}({:02X}), Value {}'.
                          format(getTimeStamp(tickCount['total']),
                                 channelNo, evtdata[i+1],
                                 evtdata[i+1],
                                 evtdata[i+2]))
                writeMidiEvent(evtdata[i:i+3])
                i += 2

            elif eventType == 0xC0:  # Program Change
                if args.verbose:
                    print('{} PC: Channel {}, Value {}'.
                          format(getTimeStamp(tickCount['total']),
                                 channelNo,
                                 evtdata[i+1]))
                writeMidiEvent(evtdata[i:i+2])
                i += 1

            elif eventType == 0xD0:  # Channel AT
                if args.verbose:
                    print('{} Channel AT: Channel {}, Value {}'.
                          format(getTimeStamp(tickCount['total']),
                                 channelNo,
                                 evtdata[i+1]))
                writeMidiEvent(evtdata[i:i+2])
                i += 1

            elif eventType == 0xE0:  # Pitch Wheel
                if args.verbose:
                    print('{} Pitch Wheel: Channel {}, Value {}'.
                          format(getTimeStamp(tickCount['total']),
                                 channelNo,
                                 evtdata[i+1] + 256 * evtdata[i+2]))
                writeMidiEvent(evtdata[i:i+3])
                i += 2

            else:
                if args.verbose:
                    print('{} Unknown MIDI Event: {:02X}'.
                          format(getTimeStamp(tickCount['total']),
                                 evtdata[i]))

        else:
            if args.verbose:
                print('{} Unknown meta event: {:02X}'.
                      format(getTimeStamp(tickCount['total']),
                             evtdata[i]))

        i += 1

    midFileName = args.file_name + '.mid'

    with open(midFileName, "wb") as fmid:
        if args.verbose:
            print('Saving file {}'.format(midFileName))
        midTruck = b'\x00\xff\x51\x03' + int(60000000/midBeatsPerMinute).to_bytes(3, 'big') + midTruck
        midHeader = b'MThd' + b'\x00\x00\x00\x06' + b'\x00\x00' + b'\x00\x01' + midTicksPerBeat.to_bytes(2, 'big')
        midTruck = b'MTrk' + len(midTruck).to_bytes(4, 'big') + midTruck
        fmid.write(midHeader)
        fmid.write(midTruck)
